"""Local Windows notifications on meaningful operational state changes only."""
import os
import subprocess

from .inventory import digest
from .release import health


def notify_if_needed(store,root):
    value=health(root)
    producer=value.get("producer",{})
    reason=producer.get("status")
    if value["status"]=="missed":
        message=f"Hôm nay đã xác nhận {value['published']}/5 summary; còn thiếu {value['missing']} bài."
    elif value["approved_available"]<5 and reason in {"waiting_quota","waiting_auth","waiting_codex","waiting_source","needs_attention"}:
        labels={"waiting_quota":"Đang chờ hạn mức Codex", "waiting_auth":"Cần đăng nhập lại Codex",
                "waiting_codex":"Codex chưa hoạt động", "waiting_source":"Đang thiếu nguồn toàn văn", "needs_attention":"Có bài cần xử lý thêm"}
        message=f"{labels[reason]}. Kho dự phòng còn {value['approved_available']} bài."
    else:
        store.set_state("alerts:last_key",None);return False
    key=digest({"date":value["date"],"status":value["status"],"reason":reason})
    if store.get_state("alerts:last_key")==key:return False
    store.set_state("alerts:last_key",key)
    store.set_state("alerts:last_message",message)
    if os.name!="nt":return True
    env=os.environ.copy();env["ASTROBRIEF_NOTICE"]=message
    script="Add-Type -AssemblyName System.Windows.Forms; Add-Type -AssemblyName System.Drawing; $notice=New-Object System.Windows.Forms.NotifyIcon; $notice.Icon=[System.Drawing.SystemIcons]::Information; $notice.Visible=$true; $notice.ShowBalloonTip(5000,'AstroBrief Việt',$env:ASTROBRIEF_NOTICE,[System.Windows.Forms.ToolTipIcon]::Info); Start-Sleep -Seconds 6; $notice.Dispose()"
    subprocess.Popen(["powershell.exe","-NoProfile","-NonInteractive","-WindowStyle","Hidden","-Command",script],
                     env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=subprocess.CREATE_NO_WINDOW)
    return True
