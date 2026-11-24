/**
 * สะพานเชื่อม "ผู้ช่วย AI" → Google Calendar (ฟรี ทำงานในบัญชี Google ของคุณเอง)
 *
 * วิธีติดตั้ง (ทำครั้งเดียว ~5 นาที):
 * 1) เปิด https://script.google.com → New project → ลบโค้ดเดิม แล้ววางโค้ดทั้งไฟล์นี้
 * 2) แก้ SECRET ด้านล่างเป็นรหัสลับของคุณเอง (ยาวๆ เดายาก เช่น ตัวอักษร+ตัวเลข 20 ตัว)
 * 3) ⚙️ Project Settings → Time zone เลือก (GMT+07:00) Bangkok
 * 4) กด Deploy → New deployment → ⚙️ เลือก Web app
 *      Execute as: Me   ·   Who has access: Anyone   → Deploy → กด Authorize ยอมรับสิทธิ์ปฏิทิน
 * 5) คัดลอก Web app URL (ลงท้าย /exec) → ในแอปผู้ช่วย: ⚙️ ตั้งค่า → 📅 Google Calendar → 🔗 เชื่อม
 *      ใส่ URL + รหัสลับ (ตรงกับข้อ 2) → ออกจากหน้าตั้งค่า → พูด "ทดสอบปฏิทิน"
 *
 * ความปลอดภัย: ใครไม่มีรหัสลับ เรียกใช้ไม่ได้ · แก้โค้ดแล้วต้อง Deploy → Manage deployments → แก้เป็น New version
 */
const SECRET = 'เปลี่ยนเป็นรหัสลับของคุณ';
const CALENDAR_ID = '';   // ว่าง = ปฏิทินหลัก · หรือใส่ ID ปฏิทินอื่น (เช่นปฏิทิน "งานซ่อม") จาก Settings ของปฏิทินนั้น

function doPost(e) {
  let d;
  try {
    d = JSON.parse(e.postData.contents);
  } catch (err) {
    return out({ ok: false, error: 'bad json' });
  }
  if (!d || d.secret !== SECRET || SECRET.indexOf('เปลี่ยน') === 0) return out({ ok: false, error: 'secret' });
  const cal = CALENDAR_ID ? CalendarApp.getCalendarById(CALENDAR_ID) : CalendarApp.getDefaultCalendar();
  if (!cal) return out({ ok: false, error: 'calendar not found' });
  const props = PropertiesService.getScriptProperties();

  if (d.action === 'ping') return out({ ok: true, cal: cal.getName() });

  if (d.action === 'create') {
    if (d.key) {                                  // กันลงซ้ำ (เช่น Job เดิม สถานะเดิม)
      const old = props.getProperty('k_' + d.key);
      if (old) return out({ ok: true, dup: true, id: old });
    }
    const opt = { description: d.description || '', location: d.location || '' };
    const ev = d.allDay
      ? cal.createAllDayEvent(d.title, new Date(d.start), opt)
      : cal.createEvent(d.title, new Date(d.start), new Date(d.end), opt);
    if (d.color) ev.setColor(String(d.color));
    if (d.reminderMin !== undefined && d.reminderMin !== null) {
      ev.removeAllReminders();
      ev.addPopupReminder(Number(d.reminderMin));
    }
    if (d.key) props.setProperty('k_' + d.key, ev.getId());
    return out({ ok: true, id: ev.getId() });
  }

  if (d.action === 'list') {
    const evs = cal.getEvents(new Date(d.start), new Date(d.end)).map(function (x) {
      return { title: x.getTitle(), start: x.getStartTime().toISOString(), end: x.getEndTime().toISOString(),
               allDay: x.isAllDayEvent() };
    });
    return out({ ok: true, events: evs });
  }
  return out({ ok: false, error: 'unknown action' });
}

function doGet() {
  return out({ ok: true, hello: 'ผู้ช่วย AI → Google Calendar พร้อมใช้งาน (ใช้ POST)' });
}

function out(o) {
  return ContentService.createTextOutput(JSON.stringify(o)).setMimeType(ContentService.MimeType.JSON);
}
