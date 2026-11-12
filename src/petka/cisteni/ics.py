"""Cleanings as an iCalendar feed (RFC 5545), for subscribing in Google, Apple or Outlook
calendars. One VEVENT per place and date. A cleaning "od 7:00" starts then (Europe/Prague); one
without a time or "před 6 hod." is an all-day event. Every event reminds the evening before at
18:00. UIDs depend only on the place and the date, so a calendar updates an event instead of
adding a new one when the harmonogram changes its time.
"""

import datetime as dt
import hashlib

TZ = "Europe/Prague"
DOMAIN = "otevrenapetka.cz"
NOTICE = "Zákaz stání podle dopravních značek."
REMIND = dt.time(18, 0)         # the evening before

VTIMEZONE = [
    "BEGIN:VTIMEZONE", f"TZID:{TZ}",
    "BEGIN:DAYLIGHT", "TZOFFSETFROM:+0100", "TZOFFSETTO:+0200", "TZNAME:CEST",
    "DTSTART:19700329T020000", "RRULE:FREQ=YEARLY;BYMONTH=3;BYDAY=-1SU", "END:DAYLIGHT",
    "BEGIN:STANDARD", "TZOFFSETFROM:+0200", "TZOFFSETTO:+0100", "TZNAME:CET",
    "DTSTART:19701025T030000", "RRULE:FREQ=YEARLY;BYMONTH=10;BYDAY=-1SU", "END:STANDARD",
    "END:VTIMEZONE",
]


def escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\r\n", "\n").replace("\n", "\\n")


def fold(line: str) -> str:
    """Lines longer than 75 octets go on as continuation lines starting with a space; a UTF-8
    character is never split."""
    out, cur, size = [], "", 0
    for ch in line:
        n = len(ch.encode())
        if size + n > 75:
            out.append(cur)
            cur, size = " ", 1
        cur += ch
        size += n
    out.append(cur)
    return "\r\n".join(out)


def uid(place_key: str, date: dt.date) -> str:
    return f"{hashlib.sha1(place_key.encode()).hexdigest()[:16]}-{date:%Y%m%d}@{DOMAIN}"


def _trigger(start: dt.datetime) -> str:
    """-PT<h>H<m>M from the start back to 18:00 the day before."""
    before = start - dt.datetime.combine(start.date() - dt.timedelta(days=1), REMIND)
    mins = int(before.total_seconds() // 60)
    return f"-PT{mins // 60}H" + (f"{mins % 60}M" if mins % 60 else "")


def event(i: dict, stamp: dt.datetime, url: str | None = None) -> list[str]:
    """The lines of one VEVENT for an item of petka.cisteni.queries.items."""
    d = i["date"]
    timed = i["time"] is not None and not i["before"]
    start = dt.datetime.combine(d, i["time"] if timed else dt.time(0))
    desc = i["text"]
    if i["time"] is not None and i["before"]:
        desc += f"\nČistí se před {i['time'].hour}:{i['time'].minute:02d}."
    desc += "\n" + NOTICE
    lines = ["BEGIN:VEVENT", f"UID:{uid(i['key'], d)}", f"DTSTAMP:{stamp:%Y%m%dT%H%M%SZ}"]
    if timed:
        lines.append(f"DTSTART;TZID={TZ}:{start:%Y%m%dT%H%M%S}")
    else:
        lines += [f"DTSTART;VALUE=DATE:{d:%Y%m%d}", f"DTEND;VALUE=DATE:{d + dt.timedelta(days=1):%Y%m%d}",
                  "TRANSP:TRANSPARENT"]
    lines += [f"SUMMARY:{escape('Blokové čištění: ' + i['street'])}", f"DESCRIPTION:{escape(desc)}",
              f"LOCATION:{escape(i['street'] + ', Pardubice')}"]
    if url:
        lines.append(f"URL:{url}")
    lines += ["BEGIN:VALARM", "ACTION:DISPLAY", f"DESCRIPTION:{escape('Zítra blokové čištění: ' + i['street'])}",
              f"TRIGGER:{_trigger(start)}", "END:VALARM", "END:VEVENT"]
    return lines


def calendar(its: list[dict], name: str, stamp: dt.datetime, url_of=lambda i: None) -> str:
    """The whole feed; `url_of(item)` gives the page an event links to."""
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", f"PRODID:-//{DOMAIN}//Cisteni ulic//CS", "CALSCALE:GREGORIAN",
             "METHOD:PUBLISH", f"X-WR-CALNAME:{escape(name)}", f"X-WR-TIMEZONE:{TZ}",
             "REFRESH-INTERVAL;VALUE=DURATION:P1D", "X-PUBLISHED-TTL:P1D", *VTIMEZONE]
    for i in its:
        lines += event(i, stamp, url_of(i))
    lines.append("END:VCALENDAR")
    return "".join(fold(x) + "\r\n" for x in lines)
