from ios import clipboard, device, location, notifications, ui, web
from ios.app.health import log_sleep

name = ui.ask_text("Your name?")
battery = device.battery_level()
notifications.notify(f"Hello {name}. Battery: {battery}%", title="py2shortcuts")

payload = web.get_json("https://example.com/data.json")
clipboard.set(payload["message"], local_only=True)

here = location.current()
print(location.maps_url(here))

# HealthKit/Shortcuts category labels remain iOS-version-sensitive. This uses
# the wire format already exercised by the project's sleep-stage probe.
log_sleep(
    "2001-01-01T12:00:00+08:00",
    "2001-01-01T12:01:00+08:00",
    stage="Awake",
)
