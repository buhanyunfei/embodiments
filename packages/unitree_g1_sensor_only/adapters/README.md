# G1 Sensor-only Adapter Placeholder

Use the existing runtime adapter work as reference. This package intentionally does not include motion commands.

Expected safe endpoints:

```http
GET /health
GET /state
GET /sensors
POST /sense/capture
POST /audio/record
```
