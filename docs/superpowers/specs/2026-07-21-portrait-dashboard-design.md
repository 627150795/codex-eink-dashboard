# Portrait Dashboard Design

Status: approved by the user on 2026-07-21.

The existing landscape dashboard remains the default layout. A new portrait
layout renders a 104x212 logical canvas and rotates it into the device's
unchanged 212x104 BLE frame. The portrait header shows task status on the left
and `API` on the right for API plans. Other plans show only the weekly quota
reset date as `M.D`, using the secondary window when available and the only
available reset window otherwise. It does not show a device battery value,
sync clock, reset icon, or time of day.

The monitor continues to validate the device through its existing BLE status
notification, but voltage is not rendered.

The new deployed configuration selects the portrait clockwise layout and polls
every 30 seconds while work is active, or every 60 seconds while idle. A frame
is still uploaded only when the rendered bitmap changes.
