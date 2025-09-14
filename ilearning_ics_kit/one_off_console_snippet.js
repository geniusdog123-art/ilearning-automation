// Paste into DevTools Console on https://lms2020.nchu.edu.tw/course/homework/<id>
(async () => {
  // helper to parse date-like string
  const parseDate = (s) => {
    // remove labels
    s = s.replace(/(繳交期限|截止|到期|截止時間)[:：]?\s*/gi, "");
    // normalize
    return new Date(s);
  };
  const rows = [...document.querySelectorAll("table tr")];
  const items = [];
  rows.forEach(tr => {
    const a = tr.querySelector('a[href*="/homework"]');
    if (!a) return;
    const tds = [...tr.querySelectorAll("td")].map(td => td.innerText.trim());
    const all = tds.join(" ");
    let dueText = tds.slice().reverse().find(t => /(繳交期限|截止|到期|Due)/i.test(t)) || all;
    const d = parseDate(dueText);
    if (isNaN(+d)) return; // skip if not a date
    items.push({ title: a.innerText.trim(), url: a.href, due: d });
  });

  const pad = (n) => (n<10? "0"+n : ""+n);
  const toICSDate = (d) => {
    const y=d.getFullYear(), m=pad(d.getMonth()+1), da=pad(d.getDate()), h=pad(d.getHours()), mi=pad(d.getMinutes());
    return `${y}${m}${da}T${h}${mi}00`;
  };

  let ics = "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//NCHU eeclass one-off//EN\r\n";
  items.forEach(it => {
    const dt = toICSDate(it.due);
    const uid = btoa(it.url + it.title).replace(/=/g,"");
    ics += "BEGIN:VEVENT\r\n";
    ics += `UID:${uid}@eeclass\r\n`;
    ics += `SUMMARY:[iLearning] ${it.title}\r\n`;
    ics += `DTSTART:${dt}\r\nDTEND:${dt}\r\n`;
    ics += `DESCRIPTION:${it.url}\r\n`;
    ics += "BEGIN:VALARM\r\nTRIGGER:-PT24H\r\nACTION:DISPLAY\r\nDESCRIPTION:Reminder\r\nEND:VALARM\r\n";
    ics += "BEGIN:VALARM\r\nTRIGGER:-PT3H\r\nACTION:DISPLAY\r\nDESCRIPTION:Reminder\r\nEND:VALARM\r\n";
    ics += "END:VEVENT\r\n";
  });
  ics += "END:VCALENDAR\r\n";

  const blob = new Blob([ics], {type: "text/calendar;charset=utf-8"});
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = "ilearning_now.ics";
  document.body.appendChild(a);
  a.click();
  URL.revokeObjectURL(a.href);
  a.remove();
  console.log(`Exported ${items.length} events to ilearning_now.ics`);
})();