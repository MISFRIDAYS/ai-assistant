"""เขียนไฟล์สไลด์ .pptx แบบไม่ต้องมีไลบรารีเพิ่ม (เปิดได้ใน WPS / PowerPoint / Google Slides)
slides = [{"title": "...", "bullets": ["...", ...], "notes": ""}] — สไลด์แรกเป็นหน้าปก
"""
import zipfile
from xml.sax.saxutils import escape

W, H = 12192000, 6858000          # 16:9
NS = ('xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
      'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
      'xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"')
THEMES = {"purple": ("5B21B6", "F7F4FF", "C026D3"), "blue": ("1E40AF", "F0F6FF", "0EA5E9"),
          "green": ("166534", "F0FDF4", "16A34A"), "dark": ("F5F3FF", "1E1433", "A78BFA")}


def _rels(items):
    body = "".join(f'<Relationship Id="{i}" Type="{t}" Target="{g}"/>' for i, t, g in items)
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            f'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">{body}</Relationships>')


R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/"


def _sp(i, name, x, y, w, h, paras, size, color, bold=False, align="l"):
    ps = "".join(
        f'<a:p><a:pPr algn="{align}"' + (' marL="342900" indent="-342900"><a:buChar char="•"/></a:pPr>' if b else '><a:buNone/></a:pPr>')
        + f'<a:r><a:rPr lang="th-TH" sz="{size}" b="{1 if bold else 0}"><a:solidFill><a:srgbClr val="{color}"/></a:solidFill>'
        '<a:latin typeface="Tahoma"/><a:cs typeface="Tahoma"/></a:rPr>'
        f'<a:t>{escape(t)}</a:t></a:r></a:p>' for t, b in paras)
    return (f'<p:sp><p:nvSpPr><p:cNvPr id="{i}" name="{name}"/><p:cNvSpPr txBox="1"/><p:nvPr/></p:nvSpPr>'
            f'<p:spPr><a:xfrm><a:off x="{x}" y="{y}"/><a:ext cx="{w}" cy="{h}"/></a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom></p:spPr>'
            f'<p:txBody><a:bodyPr wrap="square"><a:normAutofit/></a:bodyPr><a:lstStyle/>{ps}</p:txBody></p:sp>')


def _bar(i, color, y=0, h=180000):
    return (f'<p:sp><p:nvSpPr><p:cNvPr id="{i}" name="bar"/><p:cNvSpPr/><p:nvPr/></p:nvSpPr><p:spPr>'
            f'<a:xfrm><a:off x="0" y="{y}"/><a:ext cx="{W}" cy="{h}"/></a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom>'
            f'<a:solidFill><a:srgbClr val="{color}"/></a:solidFill><a:ln><a:noFill/></a:ln></p:spPr></p:sp>')


def _slide(s, idx, theme):
    fg, bg, accent = THEMES.get(theme, THEMES["purple"])
    shapes = _bar(2, accent)
    if idx == 0:
        shapes += _sp(3, "title", 700000, 2100000, W - 1400000, 1500000, [(s.get("title", ""), False)], 4800, fg, True, "ctr")
        sub = " · ".join(s.get("bullets") or [])
        if sub:
            shapes += _sp(4, "sub", 700000, 3700000, W - 1400000, 1000000, [(sub, False)], 2200, accent, False, "ctr")
    else:
        shapes += _sp(3, "title", 600000, 450000, W - 1200000, 1000000, [(s.get("title", ""), False)], 3600, fg, True)
        bl = [(b, True) for b in (s.get("bullets") or [])][:8]
        shapes += _sp(4, "body", 700000, 1600000, W - 1400000, H - 2200000, bl or [("", False)], 2400 if len(bl) <= 5 else 2000, "333333")
    return (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><p:sld {NS}><p:cSld>'
            f'<p:bg><p:bgPr><a:solidFill><a:srgbClr val="{bg}"/></a:solidFill><a:effectLst/></p:bgPr></p:bg><p:spTree>'
            '<p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr><p:grpSpPr/>'
            f'{shapes}</p:spTree></p:cSld><p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr></p:sld>')


_THEME = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><a:theme xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" name="AI">'
          '<a:themeElements><a:clrScheme name="AI"><a:dk1><a:srgbClr val="000000"/></a:dk1><a:lt1><a:srgbClr val="FFFFFF"/></a:lt1>'
          '<a:dk2><a:srgbClr val="2E1065"/></a:dk2><a:lt2><a:srgbClr val="F7F4FF"/></a:lt2><a:accent1><a:srgbClr val="7C3AED"/></a:accent1>'
          '<a:accent2><a:srgbClr val="C026D3"/></a:accent2><a:accent3><a:srgbClr val="0EA5E9"/></a:accent3><a:accent4><a:srgbClr val="16A34A"/></a:accent4>'
          '<a:accent5><a:srgbClr val="F59E0B"/></a:accent5><a:accent6><a:srgbClr val="E11D48"/></a:accent6><a:hlink><a:srgbClr val="0563C1"/></a:hlink>'
          '<a:folHlink><a:srgbClr val="954F72"/></a:folHlink></a:clrScheme><a:fontScheme name="AI"><a:majorFont><a:latin typeface="Tahoma"/>'
          '<a:ea typeface=""/><a:cs typeface="Tahoma"/></a:majorFont><a:minorFont><a:latin typeface="Tahoma"/><a:ea typeface=""/>'
          '<a:cs typeface="Tahoma"/></a:minorFont></a:fontScheme><a:fmtScheme name="AI"><a:fillStyleLst>'
          + '<a:solidFill><a:schemeClr val="phClr"/></a:solidFill>' * 3 + '</a:fillStyleLst><a:lnStyleLst>'
          + '<a:ln w="9525"><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:ln>' * 3 + '</a:lnStyleLst><a:effectStyleLst>'
          + '<a:effectStyle><a:effectLst/></a:effectStyle>' * 3 + '</a:effectStyleLst><a:bgFillStyleLst>'
          + '<a:solidFill><a:schemeClr val="phClr"/></a:solidFill>' * 3 + '</a:bgFillStyleLst></a:fmtScheme></a:themeElements></a:theme>')

_EMPTY_TREE = ('<p:cSld><p:spTree><p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr>'
               '<p:grpSpPr/></p:spTree></p:cSld>')
_MASTER = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><p:sldMaster {NS}>{_EMPTY_TREE}'
           '<p:clrMap bg1="lt1" tx1="dk1" bg2="lt2" tx2="dk2" accent1="accent1" accent2="accent2" accent3="accent3" '
           'accent4="accent4" accent5="accent5" accent6="accent6" hlink="hlink" folHlink="folHlink"/>'
           '<p:sldLayoutIdLst><p:sldLayoutId id="2147483649" r:id="rId1"/></p:sldLayoutIdLst>'
           '<p:txStyles><p:titleStyle/><p:bodyStyle/><p:otherStyle/></p:txStyles></p:sldMaster>')
_LAYOUT = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><p:sldLayout {NS} type="blank" preserve="1">'
           f'{_EMPTY_TREE}<p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr></p:sldLayout>')


def write(path, slides, theme="purple"):
    n = len(slides)
    ct = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
          '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
          '<Default Extension="xml" ContentType="application/xml"/>'
          '<Override PartName="/ppt/presentation.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"/>'
          '<Override PartName="/ppt/slideMasters/slideMaster1.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slideMaster+xml"/>'
          '<Override PartName="/ppt/slideLayouts/slideLayout1.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slideLayout+xml"/>'
          '<Override PartName="/ppt/theme/theme1.xml" ContentType="application/vnd.openxmlformats-officedocument.theme+xml"/>'
          + "".join(f'<Override PartName="/ppt/slides/slide{i + 1}.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slide+xml"/>'
                    for i in range(n)) + '</Types>')
    pres = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><p:presentation {NS}>'
            '<p:sldMasterIdLst><p:sldMasterId id="2147483648" r:id="rId1"/></p:sldMasterIdLst><p:sldIdLst>'
            + "".join(f'<p:sldId id="{256 + i}" r:id="rId{i + 3}"/>' for i in range(n))
            + f'</p:sldIdLst><p:sldSz cx="{W}" cy="{H}"/><p:notesSz cx="6858000" cy="9144000"/></p:presentation>')
    prels = [("rId1", R + "slideMaster", "slideMasters/slideMaster1.xml"), ("rId2", R + "theme", "theme/theme1.xml")] + \
            [(f"rId{i + 3}", R + "slide", f"slides/slide{i + 1}.xml") for i in range(n)]
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", ct)
        z.writestr("_rels/.rels", _rels([("rId1", R + "officeDocument", "ppt/presentation.xml")]))
        z.writestr("ppt/presentation.xml", pres)
        z.writestr("ppt/_rels/presentation.xml.rels", _rels(prels))
        z.writestr("ppt/slideMasters/slideMaster1.xml", _MASTER)
        z.writestr("ppt/slideMasters/_rels/slideMaster1.xml.rels",
                   _rels([("rId1", R + "slideLayout", "../slideLayouts/slideLayout1.xml"), ("rId2", R + "theme", "../theme/theme1.xml")]))
        z.writestr("ppt/slideLayouts/slideLayout1.xml", _LAYOUT)
        z.writestr("ppt/slideLayouts/_rels/slideLayout1.xml.rels",
                   _rels([("rId1", R + "slideMaster", "../slideMasters/slideMaster1.xml")]))
        z.writestr("ppt/theme/theme1.xml", _THEME)
        for i, s in enumerate(slides):
            z.writestr(f"ppt/slides/slide{i + 1}.xml", _slide(s, i, theme))
            z.writestr(f"ppt/slides/_rels/slide{i + 1}.xml.rels",
                       _rels([("rId1", R + "slideLayout", "../slideLayouts/slideLayout1.xml")]))
    return path
