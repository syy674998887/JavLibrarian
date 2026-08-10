"""NFO document generation."""

import re
from xml.dom import minidom
from xml.etree import ElementTree as ET


def build_nfo(data, tags, folder_name):
    root = ET.Element("movie")

    def add(parent, tag, text):
        if text is None or text == "":
            return None
        element = ET.SubElement(parent, tag)
        element.text = str(text)
        return element

    code = data.get("dvdid") or data.get("code")

    def strip_code(text):
        text = (text or "").strip()
        return text[len(code) :].strip() if text.upper().startswith(code.upper()) else text

    original_title = strip_code(data.get("title"))
    display_title = strip_code(data.get("title_cn")) or original_title

    add(root, "title", f"{code} {display_title}".strip())
    add(root, "originaltitle", original_title or display_title)
    add(root, "sorttitle", code)
    add(root, "num", code)

    unique_id = ET.SubElement(root, "uniqueid")
    unique_id.set("type", "num")
    unique_id.set("default", "true")
    unique_id.text = code

    add(root, "premiered", data.get("release"))
    add(root, "releasedate", data.get("release"))
    if data.get("release") and re.match(r"^\d{4}", data["release"]):
        add(root, "year", data["release"][:4])

    add(root, "runtime", data.get("runtime"))
    add(root, "studio", data.get("studio"))
    add(root, "maker", data.get("studio"))
    add(root, "label", data.get("label"))
    add(root, "director", data.get("director"))

    if data.get("series"):
        collection = ET.SubElement(root, "set")
        add(collection, "name", data["series"])

    for genre in data.get("genres", []):
        add(root, "genre", genre)
    for tag in tags:
        add(root, "genre", tag)
        add(root, "tag", tag)
    if data.get("series"):
        add(root, "tag", data["series"])

    for actor in data.get("actors", []):
        actor_element = ET.SubElement(root, "actor")
        add(actor_element, "name", actor.get("name"))
        add(actor_element, "type", "Actor")
        if actor.get("thumb"):
            add(actor_element, "thumb", actor["thumb"])

    add(root, "poster", "poster.jpg")
    fanart = ET.SubElement(root, "fanart")
    add(fanart, "thumb", "fanart.jpg")

    add(root, "source", data.get("source"))
    add(root, "originalfolder", folder_name)

    raw = ET.tostring(root, encoding="utf-8")
    return minidom.parseString(raw).toprettyxml(indent="  ", encoding="UTF-8")
