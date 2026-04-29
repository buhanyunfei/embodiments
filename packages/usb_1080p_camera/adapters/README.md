# USB Camera Adapter Placeholder

Existing runtime references:

```text
hub/usb_camera_adapter.py
hub/usb_camera_frame_adapter.py
nodes/camera_sensor_node.py
```

Safe endpoints should provide:

```http
GET /health
GET /sensors
POST /sense/capture
POST /audio/record
```
