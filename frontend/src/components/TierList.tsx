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
  rectSortingStrategy,
  sortableKeyboardCoordinates,
} from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import type { Tier } from "../types";

// Move a dimension into a target tier (appended at the end). Within-tier order is
// display-only — a tier weights all its chips equally — so we don't track an insert
// position. Pure: returns a new tier array that the caller persists.
function moveDimensionToTier(tiers: Tier[], dimKey: string, targetTierId: string): Tier[] {
  return tiers.map((tier) => {
    const without = tier.dimensionKeys.filter((k) => k !== dimKey);
    return tier.id === targetTierId ? { ...tier, dimensionKeys: [...without, dimKey] } : { ...tier, dimensionKeys: without };
  });
}

// Collision detection that always resolves to a TIER, never an individual chip.
//
// Both tiers and chips are registered droppables, so a naive resolver would pick a
// chip when the cursor is over one — which makes dnd-kit preview a within-tier
// insert position and shuffle the other chips around on hover. Within-tier order is
// display-only (a tier weights all its chips equally; only the tier's position
// drives the ranking), so we deliberately resolve to the tier alone: a drop just
// lands the chip in that tier and nothing shuffles while hovering.
//
// The tier whose rect contains the dragged chip's *center* wins (midpoint, not
// corners, so the wide drag overlay doesn't stray into a neighbouring tier). Falls
// back to the closest tier when the center is outside every row (gap between rows,
// or keyboard dragging with no moving rect).
function makeTierCollisionDetection(tierIds: Set<string>): CollisionDetection {
  return (args) => {
    const onlyTiers = args.droppableContainers.filter((c) => tierIds.has(String(c.id)));
    const rect = args.collisionRect;
    const cx = rect.left + rect.width / 2;
    const cy = rect.top + rect.height / 2;
    const containing = onlyTiers.filter((container) => {
      const r = args.droppableRects.get(container.id);
      return r && cx >= r.left && cx <= r.right && cy >= r.top && cy <= r.bottom;
    });
    if (containing.length > 0) {
      return containing.map((container) => ({ id: container.id }));
    }
    // Closest tier only, so `over` is always a tier id even on the fallback path.
    return closestCorners({ ...args, droppableContainers: onlyTiers });
  };
}

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
  // Display chips alphabetically by label (see the SortableContext note below).
  const sortedKeys = [...tier.dimensionKeys].sort((a, b) =>
    props.labelFor(a).localeCompare(props.labelFor(b)),
  );
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
      {/* Chips render alphabetically by their displayed label — within-tier order is
          display-only, so we present it predictably rather than in drag-arrival
          order. The SortableContext items must match this rendered order, so both
          read from the same sorted list. rectSortingStrategy (not horizontal)
          handles chips that wrap onto multiple lines. */}
      <SortableContext items={sortedKeys} strategy={rectSortingStrategy}>
        <div className="tier-chips">
          {sortedKeys.length === 0 ? (
            <span className="tier-empty">Drag criteria here</span>
          ) : (
            sortedKeys.map((key) => {
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
            const newHere = tier.dimensionKeys.filter((k) => props.newKeys.has(k));
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
  const filled = props.tiers.filter((t) => t.dimensionKeys.length > 0);
  if (filled.length === 0) return null;
  return (
    <div className="tier-summary-print">
      <h4>Importance tiers</h4>
      <dl>
        {filled.map((tier) => (
          <div key={tier.id} className="tier-summary-row">
            <dt>{tier.label}</dt>
            <dd>
              {tier.dimensionKeys
                .map((k) => props.labelFor(k))
                .sort((a, b) => a.localeCompare(b))
                .join(", ")}
            </dd>
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

  // Resolve collisions to a tier only (never a chip), so hovering never previews a
  // within-tier reorder and the chips stay put. `over.id` is therefore always a
  // tier id in the handlers below.
  const collisionDetection = makeTierCollisionDetection(new Set(tiers.map((t) => t.id)));

  function handleDragStart(event: DragStartEvent) {
    setActiveKey(String(event.active.id));
  }

  function handleDragOver(event: DragOverEvent) {
    setOverTierId(event.over ? String(event.over.id) : null);
  }

  function handleDragEnd(event: DragEndEvent) {
    const { active, over } = event;
    setActiveKey(null);
    setOverTierId(null);
    if (!over) return;
    // `over.id` is always a tier id (see collisionDetection); append into that tier.
    onChange(moveDimensionToTier(tiers, String(active.id), String(over.id)));
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
          ? { ...t, dimensionKeys: [...t.dimensionKeys, ...removed.dimensionKeys] }
          : t,
      );
    onChange(next);
  }
  function addTier() {
    // Insert a new empty tier just above the Ignore zone.
    const id = `tier-${tiers.length}-${working.length}`;
    const newTier: Tier = { id, label: `Tier ${working.length + 1}`, dimensionKeys: [], ignore: false };
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
        collisionDetection={collisionDetection}
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
