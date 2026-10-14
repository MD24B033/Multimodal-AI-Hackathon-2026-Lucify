"use client";

import { useMemo, useState } from "react";

import type { FlowMap as FlowMapData, FlowNode } from "@/lib/types";
import { Chip, Blank } from "@/components/ui";

const NODE_WIDTH = 190;
const NODE_HEIGHT = 58;
const COLUMN_GAP = 90;
const ROW_GAP = 22;

function masteryColor(mastery: number | null): string {
  if (mastery === null) return "var(--edge)";
  if (mastery >= 0.75) return "var(--mint)";
  if (mastery >= 0.45) return "var(--amber)";
  return "var(--rose)";
}

export function FlowMap({ data }: { data: FlowMapData }) {
  const [selected, setSelected] = useState<FlowNode | null>(null);

  const layout = useMemo(() => {
    const majors = data.nodes.filter((node) => node.kind === "major");
    const visible = majors.length > 0 ? majors : data.nodes;
    const visibleIds = new Set(visible.map((node) => node.id));

    const byLayer = new Map<number, FlowNode[]>();
    for (const node of visible) {
      const bucket = byLayer.get(node.layer) ?? [];
      bucket.push(node);
      byLayer.set(node.layer, bucket);
    }

    const positions = new Map<string, { x: number; y: number }>();
    const layers = [...byLayer.keys()].sort((a, b) => a - b);

    layers.forEach((layer, columnIndex) => {
      const nodes = byLayer.get(layer) ?? [];
      nodes.forEach((node, rowIndex) => {
        positions.set(node.id, {
          x: columnIndex * (NODE_WIDTH + COLUMN_GAP) + 20,
          y: rowIndex * (NODE_HEIGHT + ROW_GAP) + 20,
        });
      });
    });

    const maxRows = Math.max(...[...byLayer.values()].map((bucket) => bucket.length), 1);
    const edges = data.edges.filter(
      (edge) =>
        edge.kind === "prerequisite" && visibleIds.has(edge.source) && visibleIds.has(edge.target),
    );

    return {
      nodes: visible,
      edges,
      positions,
      width: layers.length * (NODE_WIDTH + COLUMN_GAP) + 40,
      height: maxRows * (NODE_HEIGHT + ROW_GAP) + 40,
    };
  }, [data]);

  if (data.nodes.length === 0) {
    return (
      <Blank
        title="No topic map yet"
        description="Upload course material and the topic structure with its prerequisites will be built automatically."
      />
    );
  }

  return (
    <div className="min-w-0">
      <div className="scroll-slim min-w-0 max-w-full overflow-x-auto rounded-lg border bg-[var(--glass-strong)] p-2">
        <svg
          width={Math.max(layout.width, 320)}
          height={Math.max(layout.height, 160)}
          className="min-w-full"
        >
          <defs>
            <marker
              id="flow-arrow"
              viewBox="0 0 10 10"
              refX="9"
              refY="5"
              markerWidth="6"
              markerHeight="6"
              orient="auto-start-reverse"
            >
              <path d="M 0 0 L 10 5 L 0 10 z" fill="var(--ink-soft)" />
            </marker>
          </defs>

          {layout.edges.map((edge, index) => {
            const from = layout.positions.get(edge.source);
            const to = layout.positions.get(edge.target);
            if (!from || !to) return null;
            const startX = from.x + NODE_WIDTH;
            const startY = from.y + NODE_HEIGHT / 2;
            const endX = to.x;
            const endY = to.y + NODE_HEIGHT / 2;
            const midX = (startX + endX) / 2;
            return (
              <path
                key={`${edge.source}-${edge.target}-${index}`}
                d={`M ${startX} ${startY} C ${midX} ${startY}, ${midX} ${endY}, ${endX} ${endY}`}
                fill="none"
                stroke="var(--ink-soft)"
                strokeWidth={1.2}
                opacity={0.55}
                markerEnd="url(#flow-arrow)"
              />
            );
          })}

          {layout.nodes.map((node) => {
            const position = layout.positions.get(node.id);
            if (!position) return null;
            const isSelected = selected?.id === node.id;
            return (
              <g
                key={node.id}
                transform={`translate(${position.x}, ${position.y})`}
                onClick={() => setSelected(node)}
                className="cursor-pointer"
              >
                <rect
                  width={NODE_WIDTH}
                  height={NODE_HEIGHT}
                  rx={8}
                  fill="var(--glass)"
                  stroke={isSelected ? "var(--iris)" : "var(--edge)"}
                  strokeWidth={isSelected ? 2 : 1}
                />
                <rect width={4} height={NODE_HEIGHT} rx={2} fill={masteryColor(node.mastery)} />
                <text x={14} y={23} fontSize={12} fontWeight={600} fill="var(--ink)">
                  {node.name.length > 24 ? `${node.name.slice(0, 23)}…` : node.name}
                </text>
                <text x={14} y={41} fontSize={10.5} fill="var(--ink-soft)">
                  {node.unit_count} units · {node.concept_count} concepts
                </text>
                {node.mastery !== null ? (
                  <text
                    x={NODE_WIDTH - 12}
                    y={41}
                    fontSize={10.5}
                    textAnchor="end"
                    fill={masteryColor(node.mastery)}
                    fontWeight={600}
                  >
                    {Math.round(node.mastery * 100)}%
                  </text>
                ) : null}
              </g>
            );
          })}
        </svg>
      </div>

      {selected ? (
        <div className="mt-3 rounded-lg border p-3">
          <div className="flex flex-wrap items-center gap-2">
            <h4 className="text-sm font-semibold">{selected.name}</h4>
            <Chip tone="iris">{selected.kind}</Chip>
            {selected.mastery !== null ? (
              <Chip
                tone={
                  selected.mastery >= 0.75 ? "mint" : selected.mastery >= 0.45 ? "amber" : "rose"
                }
              >
                mastery {Math.round(selected.mastery * 100)}%
              </Chip>
            ) : null}
          </div>
          {selected.summary ? (
            <p className="mt-1.5 text-sm text-[var(--ink-soft)]">{selected.summary}</p>
          ) : null}
        </div>
      ) : (
        <p className="mt-2 text-xs text-[var(--ink-soft)]">
          Arrows point from a prerequisite to the topic that depends on it. The coloured bar shows mastery.
          Select a node for details.
        </p>
      )}
    </div>
  );
}
