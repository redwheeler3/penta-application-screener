// --- Tier-list maker ---------------------------------------------------------
//
// The committee drags dimensions into importance tiers (+ an Ignore zone); higher
// tiers weigh more, Ignore weighs 0. Layout edits are the source of truth — the
// backend derives weights and re-sorts. Drag uses @dnd-kit; final placement is
// computed on drop (no live re-parenting).
import { Check, ChevronDown, ChevronUp, GripVertical, Plus, X } from "lucide-react";
import { type ReactNode, useState } from "react";
import {
  DndContext,
  DragOverlay,
  PointerSensor,
  KeyboardSensor,
  closestCorners,
  useSensor,
  useSensors,
  useDroppable,
  type CollisionDetection,
  type DragEndEvent,
  type DragOverEvent,
  type DragStartEvent,
} from "@dnd-kit/core";
import {
  SortableContext,
  useSortable,
  horizontalListSortingStrategy,
  sortableKeyboardCoordinates,
} from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import type { Tier } from "../types";

// Move a dimension into a target tier, optionally before a specific chip. Returns
// a new tier array; pure so it is easy to reason about and the caller persists it.
function moveDimensionToTier(
  tiers: Tier[],
  dimKey: string,
  targetTierId: string,
  beforeKey: string | null,
): Tier[] {
  return tiers.map((tier) => {
    const without = tier.dimension_keys.filter((k) => k !== dimKey);
    if (tier.id !== targetTierId) {
      return { ...tier, dimension_keys: without };
    }
    if (beforeKey && beforeKey !== dimKey) {
      const at = without.indexOf(beforeKey);
      if (at >= 0) {
        return {
          ...tier,
          dimension_keys: [...without.slice(0, at), dimKey, ...without.slice(at)],
        };
      }
    }
    return { ...tier, dimension_keys: [...without, dimKey] };
  });
}

function tierIndexOfKey(tiers: Tier[], dimKey: string): number {
  return tiers.findIndex((t) => t.dimension_keys.includes(dimKey));
}

// Collision detection: the tier containing the *center of the dragged chip* wins.
// Using the midpoint (not corners) keeps the wide overlay from straying into the
// neighbouring tier. Falls back to `closestCorners` when the center is outside
// every tier (gap between rows, or keyboard dragging with no moving rect).
const tierCollisionDetection: CollisionDetection = (args) => {
  const rect = args.collisionRect;
  const cx = rect.left + rect.width / 2;
  const cy = rect.top + rect.height / 2;
  const containing = args.droppableContainers.filter((container) => {
    const r = args.droppableRects.get(container.id);
    return r && cx >= r.left && cx <= r.right && cy >= r.top && cy <= r.bottom;
  });
  if (containing.length > 0) {
    return containing.map((container) => ({ id: container.id }));
  }
  return closestCorners(args);
};

// The visual chip (used in place and inside the DragOverlay). `dragging` adds the
// lifted overlay look. `isNew` badges a freshly-discovered dimension awaiting
// triage; the badge clears once it's dragged into a working tier.
function ChipBody(props: {
  label: string;
  dragging?: boolean;
  isNew?: boolean;
  onDismiss?: () => void;
}): ReactNode {
  return (
    <span className={`tier-chip${props.dragging ? " tier-chip-overlay" : ""}${props.isNew ? " tier-chip-new" : ""}`}>
      <GripVertical size={12} className="tier-chip-grip" />
      {props.label}
      {props.isNew ? (
        <span className="tier-chip-new-badge">
          New
          {props.onDismiss ? (
            <button
              type="button"
              className="tier-chip-new-dismiss"
              aria-label="Mark reviewed"
              title="Mark reviewed — keep in Ignore"
              // Stop pointerdown so the dnd-kit drag sensor never starts on the ✕.
              onPointerDown={(e) => e.stopPropagation()}
              onClick={(e) => {
                e.stopPropagation();
                props.onDismiss!();
              }}
            >
              <X size={10} strokeWidth={3} />
            </button>
          ) : null}
        </span>
      ) : null}
    </span>
  );
}

// A draggable dimension chip. While dragging, the original is hidden (opacity 0)
// and a DragOverlay copy follows the cursor across tiers (see TierList), so the
// drag isn't clipped to its tier's box.
function DimensionChip(props: {
  dimKey: string;
  label: string;
  isNew?: boolean;
  onDismiss?: () => void;
}): ReactNode {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } =
    useSortable({ id: props.dimKey });
  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
    // Hide the in-place chip entirely while it's the active drag; the overlay
    // copy is what the user sees moving.
    opacity: isDragging ? 0 : 1,
  };
  return (
    <span ref={setNodeRef} style={style} {...attributes} {...listeners}>
      <ChipBody label={props.label} isNew={props.isNew} onDismiss={props.onDismiss} />
    </span>
  );
}

// One tier row: a droppable target (so chips can land on empty space) wrapping a
// sortable context of its chips, plus tier controls.
function TierRow(props: {
  tier: Tier;
  labelFor: (key: string) => string;
  newKeys: Set<string>;
  isOver: boolean;
  canMoveUp: boolean;
  canMoveDown: boolean;
  onMoveUp: () => void;
  onMoveDown: () => void;
  onRemove: () => void;
  onRename: (label: string) => void;
  // Acknowledge "new" dimensions in place (badge ✕ / "mark all reviewed").
  onAcknowledge: (keys: string[]) => void;
}): ReactNode {
  const { tier, isOver } = props;
  // The droppable is the WHOLE row, so its rect covers the full tier height (no
  // dead space below the chips). The highlight is driven by the parent's tracked
  // `overTierId` (`isOver`), not this hook's own, which flickers over chips.
  const { setNodeRef } = useDroppable({ id: tier.id });
  return (
    <div
      ref={setNodeRef}
      className={`tier-row ${tier.ignore ? "tier-row-ignore" : ""} ${isOver ? "tier-row-over" : ""}`}
    >
      <div className="tier-row-head">
        {tier.ignore ? (
          <span className="tier-label tier-label-ignore">{tier.label}</span>
        ) : (
          <input
            className="tier-label-input"
            value={tier.label}
            aria-label="Tier name"
            onChange={(e) => props.onRename(e.target.value)}
          />
        )}
        {!tier.ignore ? (
          <div className="tier-controls">
            <button type="button" className="stepper-button" aria-label="Move tier up"
              disabled={!props.canMoveUp} onClick={props.onMoveUp}>
              <ChevronUp size={13} />
            </button>
            <button type="button" className="stepper-button" aria-label="Move tier down"
              disabled={!props.canMoveDown} onClick={props.onMoveDown}>
              <ChevronDown size={13} />
            </button>
            <button type="button" className="stepper-button" aria-label="Remove tier"
              onClick={props.onRemove}>
              <X size={13} />
            </button>
          </div>
        ) : null}
      </div>
      <SortableContext items={tier.dimension_keys} strategy={horizontalListSortingStrategy}>
        <div className="tier-chips">
          {tier.dimension_keys.length === 0 ? (
            <span className="tier-empty">Drag criteria here</span>
          ) : (
            tier.dimension_keys.map((key) => {
              // "New" badge only while the dimension is still parked in Ignore;
              // dragging it into a working tier triages it, so the badge clears.
              const isNew = props.newKeys.has(key) && Boolean(tier.ignore);
              return (
                <DimensionChip
                  key={key}
                  dimKey={key}
                  label={props.labelFor(key)}
                  isNew={isNew}
                  onDismiss={isNew ? () => props.onAcknowledge([key]) : undefined}
                />
              );
            })
          )}
          {/* Bulk-acknowledge the new dimensions in this (Ignore) row — flows after
              the chips it acts on. Only shows when at least one new flag is here. */}
          {(() => {
            const newHere = tier.dimension_keys.filter((k) => props.newKeys.has(k));
            return tier.ignore && newHere.length > 0 ? (
              <div className="tier-mark-reviewed-row">
                <button
                  type="button"
                  className="tier-mark-reviewed"
                  onClick={() => props.onAcknowledge(newHere)}
                >
                  <Check size={13} />
                  Clear all {newHere.length} "NEW" flag{newHere.length === 1 ? "" : "s"}
                </button>
              </div>
            ) : null;
          })()}
        </div>
      </SortableContext>
    </div>
  );
}

// A print-only text rendering of the importance tiers (the drag TierList is hidden
// when printing). Gives the printed ranking the context of which dimensions sit in
// which tier, so a reader sees WHY the order came out as it did.
export function TierSummaryForPrint(props: {
  tiers: Tier[];
  labelFor: (key: string) => string;
}): ReactNode {
  // Only filled tiers are worth printing; the Ignore zone is kept so a reader sees
  // what was set aside.
  const filled = props.tiers.filter((t) => t.dimension_keys.length > 0);
  if (filled.length === 0) return null;
  return (
    <div className="tier-summary-print">
      <h4>Importance tiers</h4>
      <dl>
        {filled.map((tier) => (
          <div key={tier.id} className="tier-summary-row">
            <dt>{tier.label}</dt>
            <dd>{tier.dimension_keys.map((k) => props.labelFor(k)).join(", ")}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

// The tier-list maker. `tiers` is the layout (ordered, with a final Ignore tier);
// `onChange` persists a new layout.
export function TierList(props: {
  tiers: Tier[];
  labelFor: (key: string) => string;
  newKeys: Set<string>;
  onAcknowledge: (keys: string[]) => void;
  onChange: (next: Tier[]) => void;
}): ReactNode {
  const { tiers, onChange } = props;
  // The chip being dragged (for the DragOverlay) and the tier the pointer is over
  // (drives the highlight — tracked here, not via each row's flickering isOver).
  const [activeKey, setActiveKey] = useState<string | null>(null);
  const [overTierId, setOverTierId] = useState<string | null>(null);
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 4 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  );

  // Resolve which tier an `over.id` refers to: it is either a tier id (pointer
  // over empty row space) or a chip's dimension key (resolve to its tier).
  function tierIdForOver(overId: string): string | null {
    if (tiers.some((t) => t.id === overId)) return overId;
    const idx = tierIndexOfKey(tiers, overId);
    return idx >= 0 ? tiers[idx].id : null;
  }

  function handleDragStart(event: DragStartEvent) {
    setActiveKey(String(event.active.id));
  }

  function handleDragOver(event: DragOverEvent) {
    const { over } = event;
    setOverTierId(over ? tierIdForOver(String(over.id)) : null);
  }

  function handleDragEnd(event: DragEndEvent) {
    const { active, over } = event;
    setActiveKey(null);
    setOverTierId(null);
    if (!over) return;
    const dimKey = String(active.id);
    const overId = String(over.id);
    // over.id is a tier id (dropped on empty row space) or a chip's dimension key.
    const targetTier = tiers.find((t) => t.id === overId);
    if (targetTier) {
      onChange(moveDimensionToTier(tiers, dimKey, targetTier.id, null));
      return;
    }
    const destIdx = tierIndexOfKey(tiers, overId);
    if (destIdx < 0) return;
    if (overId === dimKey) return; // dropped on itself, no-op
    onChange(moveDimensionToTier(tiers, dimKey, tiers[destIdx].id, overId));
  }

  // The Ignore tier sorts last; working tiers keep their order.
  const working = tiers.filter((t) => !t.ignore);
  const ignore = tiers.find((t) => t.ignore);
  const activeLabel = activeKey ? props.labelFor(activeKey) : null;

  function renameTier(id: string, label: string) {
    onChange(tiers.map((t) => (t.id === id ? { ...t, label } : t)));
  }
  function moveTier(idx: number, delta: number) {
    const next = [...working];
    const [moved] = next.splice(idx, 1);
    next.splice(idx + delta, 0, moved);
    onChange(ignore ? [...next, ignore] : next);
  }
  function removeTier(id: string) {
    // Removing a tier drops its chips into the first working tier (never lost).
    const target = working.find((t) => t.id !== id);
    const removed = tiers.find((t) => t.id === id);
    if (!target || !removed) return;
    const next = tiers
      .filter((t) => t.id !== id)
      .map((t) =>
        t.id === target.id
          ? { ...t, dimension_keys: [...t.dimension_keys, ...removed.dimension_keys] }
          : t,
      );
    onChange(next);
  }
  function addTier() {
    // Insert a new empty tier just above the Ignore zone.
    const id = `tier-${tiers.length}-${working.length}`;
    const newTier: Tier = { id, label: `Tier ${working.length + 1}`, dimension_keys: [], ignore: false };
    onChange(ignore ? [...working, newTier, ignore] : [...working, newTier]);
  }

  return (
    <div className="tier-list">
      <div className="tier-list-head">
        <span className="tier-list-title">Importance tiers</span>
        <button type="button" className="secondary-button tier-add" onClick={addTier}>
          <Plus size={14} /> Add tier
        </button>
      </div>
      <DndContext
        sensors={sensors}
        collisionDetection={tierCollisionDetection}
        onDragStart={handleDragStart}
        onDragOver={handleDragOver}
        onDragEnd={handleDragEnd}
      >
        {working.map((tier, idx) => (
          <TierRow
            key={tier.id}
            tier={tier}
            labelFor={props.labelFor}
            newKeys={props.newKeys}
            isOver={overTierId === tier.id}
            canMoveUp={idx > 0}
            canMoveDown={idx < working.length - 1}
            onMoveUp={() => moveTier(idx, -1)}
            onMoveDown={() => moveTier(idx, 1)}
            onRemove={() => removeTier(tier.id)}
            onRename={(label) => renameTier(tier.id, label)}
            onAcknowledge={props.onAcknowledge}
          />
        ))}
        {ignore ? (
          <TierRow
            tier={ignore}
            labelFor={props.labelFor}
            newKeys={props.newKeys}
            isOver={overTierId === ignore.id}
            canMoveUp={false}
            canMoveDown={false}
            onMoveUp={() => {}}
            onMoveDown={() => {}}
            onRemove={() => {}}
            onRename={() => {}}
            onAcknowledge={props.onAcknowledge}
          />
        ) : null}
        {/* The floating copy that follows the cursor freely across tiers — this
            is what makes cross-tier drag smooth instead of clipped to a row. */}
        <DragOverlay>
          {activeLabel ? <ChipBody label={activeLabel} dragging /> : null}
        </DragOverlay>
      </DndContext>
    </div>
  );
}
