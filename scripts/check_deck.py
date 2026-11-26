"""Check inherited school identity images and optional dual speaker notes."""
import argparse
import hashlib
import json
from pathlib import Path
import posixpath
from xml.etree import ElementTree as ET
from zipfile import ZipFile

NS = {'p': 'http://schemas.openxmlformats.org/presentationml/2006/main',
      'a': 'http://schemas.openxmlformats.org/drawingml/2006/main',
      'asvg': 'http://schemas.microsoft.com/office/drawing/2016/SVG/main',
      'r': 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'}

# Original and transparent renditions of the two separate panorama identity elements.
CAMPUS_PICTURE_MARKS = {
    '校徽': {bytes.fromhex('61f6c1f481535431b3d89dfd6ab430bcd5a03688194c104824a62b7dbece8f54'),
             bytes.fromhex('d8b0c2bbefc40a71a5281136f8f3e5ce539ccb4684fa65615c39e7dfae6ac2e2')},
    '中英文校名': {bytes.fromhex('2683abfc85d10db4d9e29913018548ee280a9ab59617103aa007406f2258278b'),
                   bytes.fromhex('6c9b24b6038f3eaf8cc5fcb7c4fa73558d8764eb2c5c337a3598055317f2c406')},
}
CAMPUS_VECTOR_MARK = tuple(bytes.fromhex(s) for s in (
    '59870d520f86d7fa3c295a60e2aac9d63b12880067169fa031b9f3e51dc82b5b',
    '97bf7703e3bd05461b02b57d00819eb8760a5059d199589c88f23e9743dbbad4',
    '513ac18c68cf865dcde772713054a95c21270b9e5a14352ebab0dc44a11c6c3a',
))

def relations(z, part):
    parent, name = posixpath.split(part)
    rels = posixpath.join(parent, '_rels', name + '.rels')
    if rels not in z.namelist():
        return {}
    result = {}
    for rel in ET.fromstring(z.read(rels)):
        if rel.get('TargetMode') != 'External':
            ref = posixpath.normpath(posixpath.join(parent, rel.get('Target'))).lstrip('/')
            result[rel.get('Id')] = (rel.get('Type').split('/')[-1], ref)
    return result

def related(rels, kind):
    return [part for typ, part in rels.values() if typ == kind]

def vector_marks(root):
    """Identify three adjacent identity paths, including ungrouped WPS artwork."""
    marks = set()
    for group in root.findall('.//p:grpSp', NS) + root.findall('.//p:spTree', NS):
        paths = group.findall('p:sp/p:spPr/a:custGeom/a:pathLst', NS)
        digests = [hashlib.sha256(ET.tostring(p)).digest() for p in paths]
        marks.update(tuple(digests[i:i+3]) for i in range(len(digests)-2))
    return marks

def slide_layout_role(z, slide):
    layouts = related(relations(z, slide), 'slideLayout')
    if layouts:
        canvas = ET.fromstring(z.read(layouts[0])).find('p:cSld', NS)
        if canvas is not None:
            return canvas.get('name', '')
    return ''


def inspect_slide(z, slide, fingerprints, check_notes, approved_marks, alternate_images=None, brand_images=None, expected=None):
    own = relations(z, slide)
    levels = [slide]
    if ET.fromstring(z.read(slide)).get('showMasterSp') not in ('0','false'):
        for layout in related(own, 'slideLayout'):
            levels.append(layout)
            if ET.fromstring(z.read(layout)).get('showMasterSp') not in ('0','false'):
                levels.extend(related(relations(z, layout), 'slideMaster'))
    images = set()
    found_marks = set()
    has_logo_backing = False
    for level in levels:
        rels = relations(z, level)
        root = ET.fromstring(z.read(level))
        found_marks.update(vector_marks(root))
        if root.find(".//p:sp/p:nvSpPr/p:cNvPr[@name='底版·校标衬底']", NS) is not None:
            has_logo_backing = True
        for blip in root.findall('.//a:blip', NS) + root.findall('.//asvg:svgBlip', NS):
            rid = blip.get('{'+NS['r']+'}embed')
            if rid in rels and rels[rid][0] == 'image':
                images.add(hashlib.sha256(z.read(rels[rid][1])).digest())
    alternate_images = alternate_images or {}
    missing = [] if found_marks & approved_marks else [
        name for name, sha in fingerprints.items()
        if sha not in images and images.isdisjoint(alternate_images.get(name, ()))
    ]
    brands = {name for name, digests in (brand_images or {}).items() if not images.isdisjoint(digests)}
    if expected:
        missing = [] if brands == {expected} else [f'主题标识应为{expected}，实际识别到{"/".join(sorted(brands)) or "无"}']
    elif brands:
        missing = []
    if has_logo_backing:
        missing.append('请移除校标衬底并使用透明标识')
    if check_notes:
        parts = related(own, 'notesSlide')
        note = ''.join(n.text or '' for part in parts for n in ET.fromstring(z.read(part)).findall('.//a:t', NS))
        missing.extend(tag for tag in ['【专家版】','【自用通俗版】'] if tag not in note)
    return missing

def main():
    assets = Path(__file__).resolve().parents[1] / 'assets'
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('deck', type=Path)
    parser.add_argument('--seal',type=Path,default=assets/'校徽.png')
    parser.add_argument('--wordmark',type=Path,default=assets/'中英文校名.png')
    parser.add_argument('--dual-notes',action='store_true')
    parser.add_argument('--theme', help='按主题编号或全名核对各版式使用的校标颜色')
    args = parser.parse_args()
    brand_images = {}
    expected_theme = None
    if args.theme:
        catalog = json.loads((assets.parent/'references'/'主题目录.json').read_text(encoding='utf8'))
        expected_theme = next((t for t in catalog if args.theme in (str(t['id']),f"{t['id']:02}",t['name'])),None)
        if expected_theme is None:
            parser.error('主题未收录，请输入本技能内的主题编号或名称。')
        if args.seal != assets/'校徽.png' or args.wordmark != assets/'中英文校名.png':
            parser.error('--theme 使用内置主题的图像指纹；核对自定义图片请使用 --seal 和 --wordmark。')
    imgs = {label:hashlib.sha256(path.read_bytes()).digest() for label,path in [('校徽',args.seal),('中英文校名',args.wordmark)]}
    approved_marks = set()
    alternate_images = {}
    if args.seal == assets/'校徽.png' and args.wordmark == assets/'中英文校名.png':
        for f in (assets/'主题标识').glob('*'):
            if f.suffix.lower() in ('.png', '.svg'):
                brand_images.setdefault(f.stem, set()).add(hashlib.sha256(f.read_bytes()).digest())
        if (assets/'中飞院答辩参考封面_万瑞飞机版.pptx').is_file():
            with ZipFile(assets/'中飞院答辩参考封面_万瑞飞机版.pptx') as alternate:
                root = ET.fromstring(alternate.read('ppt/slides/slide1.xml'))
                for group in root.findall('.//p:grpSp', NS):
                    paths = group.findall('p:sp/p:spPr/a:custGeom/a:pathLst', NS)
                    if len(paths) == 3:
                        approved_marks.add(tuple(hashlib.sha256(ET.tostring(p)).digest() for p in paths))
        approved_marks.add(CAMPUS_VECTOR_MARK)
        alternate_images = CAMPUS_PICTURE_MARKS
    with ZipFile(args.deck) as z:
        presentation='ppt/presentation.xml'
        rels=relations(z,presentation)
        ids=ET.fromstring(z.read(presentation)).findall('p:sldIdLst/p:sldId',NS)
        if not ids:
            raise SystemExit('演示文件没有幻灯片')
        bad=0
        for i,el in enumerate(ids,1):
            slide=rels[el.get('{'+NS['r']+'}id')][1]
            expected = None
            if expected_theme:
                role = slide_layout_role(z,slide)
                key = 'cover' if role in ('封面','致谢') else 'chapter' if role=='章节过渡' else 'body'
                expected = expected_theme[key]
            issues=inspect_slide(z,slide,imgs,args.dual_notes,approved_marks,alternate_images,brand_images,expected)
            if issues:
                print(f'第 {i} 页需检查 ' + '、'.join(issues))
                bad+=1
        print(f'检查 {len(ids)} 页；发现 {bad} 页需要复查。')
        return int(bool(bad))

if __name__=='__main__':
    raise SystemExit(main())
