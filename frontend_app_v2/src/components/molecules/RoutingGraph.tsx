import { useId } from 'react';
import { motion } from 'framer-motion';
import { Clock } from 'lucide-react';
import { cn } from '@/lib/cn';
import { BADGE, CARD } from '@/lib/tokens';
// Nama komponen sengaja sama dengan nama tipe graph-nya (spesifikasi Fase 15),
// jadi tidak perlu alias impor: `RoutingGraph` di posisi tipe = tipe, di posisi
// nilai = komponen (TypeScript memisahkan value-space dan type-space).
import type { DagNode, RoutingGraph } from '@/types/routing';

/**
 * RoutingGraph - visualisasi DAG routing (supervisor: monitor, admin: editor).
 *
 * - Edge digambar sebagai `<line>` di SVG; loop rework = garis putus-putus coral
 *   (`stroke-dasharray` 4 4) dengan marker panah sendiri.
 * - Node adalah `motion.div` yang bisa di-drag (`dragMomentum={false}`); posisi baru
 *   dilaporkan lewat `onDrag` supaya pemanggil yang menyimpan state.
 * - Simpul bottleneck: border coral + ring + `animate-pulse` (selalu ada teks juga).
 */

const NODE_WIDTH = 160;
const CANVAS_PADDING_X = 48;
const CANVAS_PADDING_Y = 220;

interface RoutingGraphProps {
  graph: RoutingGraph;
  selectedId?: string;
  onSelect?: (id: string) => void;
  onDrag?: (id: string, pos: { x: number; y: number }) => void;
  className?: string;
}

function isBottleneckNode(node: DagNode): boolean {
  return node.status === 'bottleneck';
}

export function RoutingGraph({ graph, selectedId, onSelect, onDrag, className }: RoutingGraphProps) {
  const uid = useId().replace(/:/g, '');
  const arrowId = `${uid}-arrow`;
  const reworkArrowId = `${uid}-arrow-rework`;

  const nodeById = new Map(graph.nodes.map((node) => [node.id, node]));

  if (graph.nodes.length === 0) {
    return (
      <div className={cn(CARD, 'flex items-center gap-2 text-sm text-muted-foreground', className)}>
        <Clock className="h-4 w-4 shrink-0" aria-hidden="true" />
        Graf routing belum diatur
      </div>
    );
  }

  const canvasWidth =
    Math.max(...graph.nodes.map((node) => node.position.x + NODE_WIDTH)) + CANVAS_PADDING_X;
  const canvasHeight =
    Math.max(...graph.nodes.map((node) => node.position.y)) + CANVAS_PADDING_Y;

  const edgeLines = graph.edges.flatMap((edge) => {
    const from = nodeById.get(edge.from);
    const to = nodeById.get(edge.to);
    if (from === undefined || to === undefined) return [];

    return [{ edge, from, to }];
  });

  return (
    <div className={cn('overflow-auto', className)}>
      <div className="relative" style={{ width: canvasWidth, height: canvasHeight }}>
        <svg className="pointer-events-none absolute inset-0 h-full w-full" aria-hidden="true">
          <defs>
            <marker
              id={arrowId}
              viewBox="0 0 10 10"
              refX="9"
              refY="5"
              markerWidth="6"
              markerHeight="6"
              orient="auto"
            >
              <path d="M0 0 L10 5 L0 10 Z" className="fill-muted-foreground" />
            </marker>
            <marker
              id={reworkArrowId}
              viewBox="0 0 10 10"
              refX="9"
              refY="5"
              markerWidth="6"
              markerHeight="6"
              orient="auto"
            >
              <path d="M0 0 L10 5 L0 10 Z" className="fill-accent-coral" />
            </marker>
          </defs>

          {edgeLines.map(({ edge, from, to }) => (
            <line
              key={edge.id}
              x1={from.position.x + NODE_WIDTH / 2}
              y1={from.position.y + 72}
              x2={to.position.x + NODE_WIDTH / 2}
              y2={to.position.y}
              strokeWidth={1.5}
              strokeDasharray={edge.isRework ? '4 4' : undefined}
              markerEnd={edge.isRework ? `url(#${reworkArrowId})` : `url(#${arrowId})`}
              className={cn(edge.isRework ? 'stroke-accent-coral' : 'stroke-border')}
            />
          ))}
        </svg>

        {graph.nodes.map((node) => {
          const isSelected = node.id === selectedId;

          return (
            <motion.div
              key={node.id}
              drag={onDrag !== undefined}
              dragMomentum={false}
              onDragEnd={(_event, info) => {
                onDrag?.(node.id, {
                  x: node.position.x + info.offset.x,
                  y: node.position.y + info.offset.y,
                });
              }}
              onClick={() => onSelect?.(node.id)}
              onKeyDown={(event) => {
                if (onSelect === undefined) return;
                if (event.key !== 'Enter' && event.key !== ' ') return;

                event.preventDefault();
                onSelect(node.id);
              }}
              role={onSelect !== undefined ? 'button' : undefined}
              tabIndex={onSelect !== undefined ? 0 : undefined}
              aria-label={`Work center ${node.label}`}
              style={{ left: node.position.x, top: node.position.y, width: NODE_WIDTH }}
              className={cn(
                'absolute cursor-grab rounded-lg border-2 bg-card p-3 shadow-pill transition-colors active:cursor-grabbing',
                // Urutan penting: kelas selected ditulis terakhir supaya menang saat bentrok.
                isBottleneckNode(node)
                  ? 'animate-pulse border-accent-coral ring-2 ring-accent-coral/30'
                  : 'border-border',
                isSelected ? 'border-accent-blue ring-2 ring-accent-blue/30' : undefined,
              )}
            >
              <p className="text-sm font-semibold tracking-tight text-foreground">{node.label}</p>
              {node.step_no !== undefined ? (
                <p className="text-[11px] uppercase tracking-wider text-muted-foreground/80">
                  Step {node.step_no}
                </p>
              ) : null}
              {node.smv !== undefined || node.maxWip !== undefined ? (
                <p className="text-[11px] uppercase tracking-wider text-muted-foreground/80">
                  SMV {node.smv ?? '-'} - max WIP {node.maxWip ?? '-'}
                </p>
              ) : null}

              {node.capability !== undefined && node.capability.length > 0 ? (
                <ul className="mt-2 flex flex-wrap gap-1">
                  {node.capability.slice(0, 2).map((capability) => (
                    <li key={capability}>
                      <span className={cn(BADGE, 'bg-muted text-muted-foreground')}>{capability}</span>
                    </li>
                  ))}
                </ul>
              ) : null}
            </motion.div>
          );
        })}
      </div>
    </div>
  );
}
