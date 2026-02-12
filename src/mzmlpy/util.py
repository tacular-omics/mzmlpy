import xml.etree.ElementTree as ElementTree


def get_tag(element: ElementTree.Element) -> str:
    return element.tag.split("}")[-1] if "}" in element.tag else element.tag
