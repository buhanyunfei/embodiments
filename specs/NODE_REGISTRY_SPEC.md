# Node Registry Spec v0.3

The registry is the normalized list of all nodes a package introduces or references, including physical hardware, sensors, and software agents.

In the slim layout, the registry is inlined inside `embodiment.yaml`:

```yaml
registry:
  schema: embodiment_node_registry/v2
  nodes: [...]
```

For backward compatibility, packages may also keep the registry in a separate file at `registry/nodes.yaml`.

## Schema

```yaml
schema: embodiment_node_registry/v2
generated_at: 1714377600.0          # optional epoch timestamp
nodes:
  - id: <node_id>
    name: Human-readable Name
    node_type: physical_robot | sensor | actuator | perception_model | agent_node
    participant_type: robot_node | sensor_node | agent_node
    agent_subtype: llm_agent | human_operator       # required when participant_type is agent_node
    role: robot_local_view | external_view | audio_input | planner | supervisor | executor | support_node
    safe_capabilities: [observe, perceive, listen, plan, approve, ...]
    sensors: [rgb_camera, depth_camera, ...]         # optional, for hardware nodes
    limits:
      sensor_only: true
      movement_allowed: false
      manipulation_allowed: false
    standalone_only: false
    endpoint_configured: false
    real_device: true                                # false for virtual/software nodes
    agent_ref: null                                  # optional planner-side handle
    parent_robot: <node_id>                          # optional, for sensors owned by a robot
    tool_interface:                                  # optional, defines callable operations
      protocol: http | ros | grpc | local | tool_call
      endpoint: <url_or_topic_or_null>
      operations:
        - operation_id: <slug>
          description: <one-line what this operation does>
          method: GET | POST | PUT | DELETE          # for http protocol
          path: <url_path>                           # for http protocol
          topic: <ros_topic>                         # for ros protocol
          input_schema:
            type: object
            properties: {...}
          output_schema:
            type: object
            properties: {...}
          latency_estimate_ms: <int>
          safety_class: safe | confirmation | supervisor | forbidden
    metadata: {}                                    # optional, arbitrary
```

## Node Types

### Physical Nodes

| node_type | participant_type | Description |
|-----------|-----------------|-------------|
| `physical_robot` | `robot_node` | Robot body with potential sensors and actuators |
| `sensor` | `sensor_node` | Standalone sensor (camera, microphone, IMU) |
| `actuator` | `robot_node` | Standalone actuator (speaker, motor) |

### Software Nodes

| node_type | participant_type | agent_subtype | Description |
|-----------|-----------------|---------------|-------------|
| `perception_model` | `agent_node` | `llm_agent` | VLM, object detection, SLAM |
| `agent_node` | `agent_node` | `llm_agent` | LLM-based planner or executor |
| `agent_node` | `agent_node` | `human_operator` | Human in the loop |

## Tool Interface

The `tool_interface` field defines how external systems (Codex, OpenClaw) can call operations on a node. This enables the Context + Tools integration pattern.

### Hardware Node Tool Interface

```yaml
tool_interface:
  protocol: http
  endpoint: "http://${G1_HOST}:8080"
  operations:
    - operation_id: capture_frame
      description: "Capture a single RGB frame from this sensor"
      method: POST
      path: /sensors/capture
      input_schema:
        type: object
        properties:
          resolution:
            type: string
            enum: ["720p", "1080p"]
            default: "1080p"
          format:
            type: string
            enum: ["jpg", "png"]
            default: "jpg"
      output_schema:
        type: object
        properties:
          frame_path:
            type: string
            description: "Path to the captured frame file"
          timestamp:
            type: number
            description: "Unix epoch of capture"
      latency_estimate_ms: 200
      safety_class: safe
    - operation_id: health_check
      description: "Check sensor connectivity and readiness"
      method: GET
      path: /health
      input_schema: {}
      output_schema:
        type: object
        properties:
          status:
            type: string
            enum: ["healthy", "degraded", "offline"]
      latency_estimate_ms: 50
      safety_class: safe
```

### Agent Node Tool Interface

Agent nodes use `protocol: tool_call` to indicate they are invoked as abstract tool calls rather than network endpoints:

```yaml
tool_interface:
  protocol: tool_call
  endpoint: null
  operations:
    - operation_id: request_approval
      description: "Request human operator approval for a gated action"
      input_schema:
        type: object
        properties:
          action:
            type: string
            description: "The action requiring approval"
          context:
            type: string
            description: "Why this action is needed"
          risk_level:
            type: string
            enum: ["low", "medium", "high"]
        required: ["action", "context"]
      output_schema:
        type: object
        properties:
          approved:
            type: boolean
          reason:
            type: string
      latency_estimate_ms: null    # human response time is unpredictable
      safety_class: safe
```

### LLM Agent Tool Interface

```yaml
tool_interface:
  protocol: tool_call
  endpoint: null
  operations:
    - operation_id: generate_plan
      description: "Generate an execution plan for a physical task"
      input_schema:
        type: object
        properties:
          task:
            type: string
          constraints:
            type: object
          available_nodes:
            type: array
            items: {type: string}
        required: ["task"]
      output_schema:
        type: object
        properties:
          plan_steps:
            type: array
            items:
              type: object
              properties:
                step_id: {type: integer}
                node_id: {type: string}
                operation_id: {type: string}
                ordering: {type: string, enum: ["serial", "parallel", "conditional"]}
          confidence:
            type: number
      latency_estimate_ms: 3000
      safety_class: safe
    - operation_id: describe_scene
      description: "Describe the current scene from provided frames"
      input_schema:
        type: object
        properties:
          frame_paths:
            type: array
            items: {type: string}
        required: ["frame_paths"]
      output_schema:
        type: object
        properties:
          description: {type: string}
          objects_detected: {type: array, items: {type: string}}
      latency_estimate_ms: 2000
      safety_class: safe
```

## Required Fields per Node

- `id` — unique within the registry
- `node_type`
- `participant_type`
- `safe_capabilities` (non-empty)
- `agent_subtype` — required when `participant_type: agent_node`
- `real_device` — required; `false` for agent_nodes

## Safety Rules

1. A node must not declare `safe_capabilities` that include any forbidden action under the package's safety policy.

2. If `limits.sensor_only: true` then `safe_capabilities` must be a subset of:
   ```
   observe, inspect, listen, perceive, wait, standby, health_check
   ```

3. `tool_interface.operations[].safety_class` must be consistent with the package safety profile:
   - Operations classified as `forbidden` are NOT exposed as callable tools
   - Operations classified as `confirmation` include a built-in human approval step
   - Operations classified as `supervisor` require both confirmation and supervisor signoff

## Standalone-Only Nodes

If `standalone_only: true`, the composer must not include this node in any auto-generated collaboration graph. The package still describes the node for agent awareness.

## Backwards Compatibility

`embodiment_node_registry/v1` is accepted with a deprecation warning. The builder infers:
- `participant_type` from `node_type` (physical_robot/actuator → robot_node, sensor → sensor_node, perception_model → agent_node)
- `real_device: true` for all v1 nodes
- Missing `tool_interface` is valid (node has no callable operations)
