# Embodiment Composer

Embodiment Composer automatically creates new embodiment packages from connected robots/hardware and the current topology.

It is not an embodiment package itself. It is a composition tool.

## Goal

Given:

- existing embodiment packages;
- current topology nodes;
- robot/hardware profiles;
- user collaboration policy;

produce:

1. instance embodiment package for a newly connected robot/hardware;
2. collaboration graph packages between compatible nodes;
3. safety-filtered topology proposals.

## Key rule

Automatic composition must respect user policy.

If a node declares:

```yaml
collaboration_policy:
  standalone_only: true
```

then composer must not generate collaboration graphs involving that node.

## Inputs

```text
hub/topology_snapshot.json
embodiments/policies/default_composition_policy.yaml
embodiments/packages/*/embodiment.yaml
```

## Output

```text
embodiments/generated/<package_id>/
  embodiment.yaml
  README.md
  graphs/*.yaml
  profiles/*.md
```

## Commands

Preview without writing:

```bash
python embodiments/composer/compose_embodiments.py preview \
  --topology hub/topology_snapshot.json \
  --packages embodiments/packages \
  --policy embodiments/policies/default_composition_policy.yaml
```

Generate packages:

```bash
python embodiments/composer/compose_embodiments.py generate \
  --topology hub/topology_snapshot.json \
  --packages embodiments/packages \
  --policy embodiments/policies/default_composition_policy.yaml \
  --out embodiments/generated
```

Build generated packages:

```bash
python embodiments/builder/build_embodiment.py build-all embodiments/generated --out embodiments/dist
```
