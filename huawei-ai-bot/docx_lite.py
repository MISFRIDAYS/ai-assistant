"""เขียนไฟล์ Word (.docx) ไม่ต้องมีไลบรารีเพิ่ม — เปิด/แก้ต่อใน WPS ได้
write(path, title, paragraphs) · บรรทัดที่ขึ้นต้นด้วย "# " = หัวข้อ · "- " = รายการ
"""
import zipfile
from xml.sax.saxutils import escape

_W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'


def _run(text, size=32, bold=False):
    b = "<w:b/><w:bCs/>" if bold else ""
    return (f'<w:r><w:rPr><w:rFonts w:ascii="Tahoma" w:hAnsi="Tahoma" w:cs="Tahoma"/>{b}'
            f'<w:sz w:val="{size}"/><w:szCs w:val="{size}"/></w:rPr><w:t xml:space="preserve">{escape(text)}</w:t></w:r>')


def _p(text, size=32, bold=False, center=False, bullet=False):
    jc = '<w:jc w:val="center"/>' if center else ""
    ind = '<w:ind w:left="567" w:hanging="283"/>' if bullet else ""
    return f'<w:p><w:pPr>{jc}{ind}<w:spacing w:after="160"/></w:pPr>{_run(("• " if bullet else "") + text, size, bold)}</w:p>'


def write(path, title, text):
    body = []
    if title:
        body.append(_p(title, 44, True, True))
    for line in (text or "").splitlines():
        s = line.rstrip()
        if not s.strip():
            body.append("<w:p/>")
        elif s.lstrip().startswith("#"):
            body.append(_p(s.lstrip("# ").strip(), 36, True))
        elif s.lstrip()[:2] in ("- ", "• ", "* "):
            body.append(_p(s.lstrip()[2:], 32, bullet=True))
        else:
            body.append(_p(s, 32))
    doc = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:document {_W}><w:body>{"".join(body)}'
           '<w:sectPr><w:pgSz w:w="11906" w:h="16838"/><w:pgMar w:top="1440" w:right="1440" w:bottom="1440" w:left="1440" '
           'w:header="708" w:footer="708" w:gutter="0"/></w:sectPr></w:body></w:document>')
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                   '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                   '<Default Extension="xml" ContentType="application/xml"/>'
                   '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>')
        z.writestr("_rels/.rels",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>')
        z.writestr("word/document.xml", doc)
    return path
