"""Add the CAFUC library as a native, adjustable background picture on selected slides."""
import argparse
from pathlib import Path
from pptx import Presentation
from pptx.oxml.xmlchemy import OxmlElement

ASSET = Path(__file__).resolve().parents[1] / "assets" / "中飞院图书馆_透明原图.png"
LAYER = "中飞院图书馆 · 正文背景"

def page_numbers(spec, count):
    selected = set()
    for item in spec.split(","):
        bounds = item.strip().split("-")
        if len(bounds) not in (1, 2) or not all(s.isdigit() for s in bounds):
            raise ValueError("页码应为 3-32 或 3-8,10 的形式")
        first, last = int(bounds[0]), int(bounds[-1])
        if not 1 <= first <= last <= count:
            raise ValueError(f"页码 {item} 超出演示文稿范围")
        selected.update(range(first, last + 1))
    return sorted(selected)

def add_watermark(presentation, number, transparency):
    slide = presentation.slides[number - 1]
    for old in list(slide.shapes):
        if old.name == LAYER:
            old._element.getparent().remove(old._element)
    # Anchor just below the header on the right of a 16:9 school slide.
    # Keeping the photo in the title band leaves the chart and frame area clear.
    width = round(presentation.slide_width * 0.260)
    right = round(presentation.slide_width * 0.031)
    top = round(presentation.slide_height * 0.091)
    picture = slide.shapes.add_picture(str(ASSET), presentation.slide_width-width-right, top, width=width)
    picture.name = LAYER
    blip = picture._element.xpath("./p:blipFill/a:blip")[0]
    alpha = OxmlElement("a:alphaModFix")
    alpha.set("amt", str(round(1000 * (100 - transparency))))
    blip.append(alpha)
    tree = slide.shapes._spTree
    tree.remove(picture._element)
    group_properties = tree.xpath("./p:grpSpPr")[0]
    group_properties.addnext(picture._element)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--pages", required=True, help="按放映顺序选择正文，如 3-32")
    parser.add_argument("--transparency", type=float, default=75.0,
                        help="在原始透明 PNG 上额外施加的透明度百分比，默认 75")
    args = parser.parse_args()
    if args.input.resolve() == args.output.resolve():
        parser.error("请使用另一个输出文件名，以保留源稿")
    if not 0 <= args.transparency <= 100:
        parser.error("透明度应在 0 至 100 之间")
    deck = Presentation(args.input)
    try:
        pages = page_numbers(args.pages, len(deck.slides))
    except ValueError as err:
        parser.error(str(err))
    for number in pages:
        add_watermark(deck, number, args.transparency)
    deck.save(args.output)
    print(f"已设置 {len(pages)} 张正文页的图书馆底图。")

if __name__ == "__main__":
    main()
