// --- Tier-list maker ---------------------------------------------------------
//
// The committee drags dimensions into importance tiers (+ an Ignore zone); higher
// tiers weigh more, Ignore weighs 0. Layout edits are the source of truth — the
// backend derives weights and re-sorts. Drag uses @dnd-kit; final placement is
// computed on drop (no live re-parenting).
import { Check, ChevronDown, ChevronUp, GripVertical, Plus, Star, X } from "lucide-react";
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

// The visual-only chip shell used inside the DragOverlay (the copy that follows the
// cursor). The in-place interactive chip is `DimensionChip` below; this just mirrors
// its look while dragging. `isFav` shows the kept-star so the dragged copy matches.
// A chip's triage badge: "new" (never seen — amber alarm, always in Ignore) or
// "revived" (seen before, dropped, now back — blue heads-up, may be auto-placed in a
// working tier). null when the chip needs no attention. Both are the SAME flag
// underneath (see revived_flag_keys); this is only the display label + colour.
type ChipBadge = "new" | "revived" | null;

function ChipBody(props: {
  label: string;
  dragging?: boolean;
  badge?: ChipBadge;
  isFav?: boolean;
}): ReactNode {
  const badgeClass =
    props.badge === "new" ? " tier-chip-new" : props.badge === "revived" ? " tier-chip-revived" : "";
  return (
    <span className={`tier-chip${props.dragging ? " tier-chip-overlay" : ""}${badgeClass}`}>
      <GripVertical size={12} className="tier-chip-grip" />
      <span className="tier-chip-label">{props.label}</span>
      {props.isFav ? <Star size={12} className="tier-chip-fav-icon" fill="currentColor" /> : null}
      {props.badge === "new" ? <span className="tier-chip-new-badge">New</span> : null}
      {props.badge === "revived" ? <span className="tier-chip-revived-badge">Revived</span> : null}
    </span>
  );
}

// An interactive dimension chip: the ONE place a criterion lives now (the separate
// criteria cloud is gone). The WHOLE chip is draggable (as it was originally); a
// plain click — which the drag sensor's 4px activation distance lets through without
// starting a drag — opens its description. Picking it up to drag also opens the
// description (see handleDragStart). The ★ keeps it across re-runs. While dragging,
// the original is hidden (opacity 0) and a DragOverlay copy follows the cursor.
function DimensionChip(props: {
  dimKey: string;
  label: string;
  badge?: ChipBadge;
  isFav: boolean;
  isOpen: boolean;
  onDismiss?: () => void;
  onToggleFav: () => void;
  onOpen: () => void;
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
  const badgeClass =
    props.badge === "new" ? " tier-chip-new" : props.badge === "revived" ? " tier-chip-revived" : "";
  return (
    <span
      ref={setNodeRef}
      style={style}
      className={`tier-chip tier-chip-draggable${badgeClass}${props.isOpen ? " tier-chip-open" : ""}`}
      // The whole chip carries the drag listeners; a click that doesn't move opens
      // the description (the 4px activation distance distinguishes click from drag).
      {...attributes}
      {...listeners}
      onClick={props.onOpen}
    >
      <GripVertical size={12} className="tier-chip-grip" />
      <span className="tier-chip-label">{props.label}</span>
      <button
        type="button"
        className={`tier-chip-fav${props.isFav ? " is-fav" : ""}`}
        aria-pressed={props.isFav}
        title={props.isFav ? "Favourited — kept on re-run" : "Favourite — keep this axis on re-run"}
        // Stop the drag sensor and the chip's open-on-click from firing on the ★.
        onPointerDown={(e) => e.stopPropagation()}
        onClick={(e) => {
          e.stopPropagation();
          props.onToggleFav();
        }}
      >
        <Star size={12} fill={props.isFav ? "currentColor" : "none"} />
      </button>
      {props.badge ? (
        <span className={props.badge === "new" ? "tier-chip-new-badge" : "tier-chip-revived-badge"}>
          {props.badge === "new" ? "New" : "Revived"}
          {props.onDismiss ? (
            <button
              type="button"
              className="tier-chip-new-dismiss"
              aria-label="Mark reviewed"
              title={
                props.badge === "new"
                  ? "Mark reviewed — keep in Ignore"
                  : "Mark reviewed — keep this placement"
              }
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

// One tier row: a droppable target (so chips can land on empty space) wrapping a
// sortable context of its chips, plus tier controls.
function TierRow(props: {
  tier: Tier;
  labelFor: (key: string) => string;
  newKeys: Set<string>;
  revivedKeys: Set<string>;
  favourited: Set<string>;
  openKey: string | null;
  isOver: boolean;
  canMoveUp: boolean;
  canMoveDown: boolean;
  onMoveUp: () => void;
  onMoveDown: () => void;
  onRemove: () => void;
  onRename: (label: string) => void;
  // Acknowledge "new" dimensions in place (badge ✕ / "mark all reviewed").
  onAcknowledge: (keys: string[]) => void;
  onToggleFav: (key: string, favourited: boolean) => void;
  onOpen: (key: string) => void;
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
              // Badge kind, both from the ONE flagged set (props.newKeys) with the
              // revived subset split out for its label/colour:
              //  - "revived" (seen before, back after a gap): shows in ANY tier,
              //    because carry-forward auto-places it into its restored tier and we
              //    still want it flagged there (RQ4 — a revived dim silently at weight
              //    is the most important to surface).
              //  - "new" (never seen): only while still parked in Ignore, as before —
              //    a member dragging it to a working tier triages it, clearing the flag.
              const flagged = props.newKeys.has(key);
              const revived = props.revivedKeys.has(key);
              const badge: ChipBadge = revived
                ? "revived"
                : flagged && tier.ignore
                  ? "new"
                  : null;
              const isFav = props.favourited.has(key);
              return (
                <DimensionChip
                  key={key}
                  dimKey={key}
                  label={props.labelFor(key)}
                  badge={badge}
                  isFav={isFav}
                  isOpen={props.openKey === key}
                  onDismiss={badge ? () => props.onAcknowledge([key]) : undefined}
                  onToggleFav={() => props.onToggleFav(key, !isFav)}
                  onOpen={() => props.onOpen(key)}
                />
              );
            })
          )}
          {/* Bulk-acknowledge the flagged dimensions in this (Ignore) row — flows
              after the chips it acts on. Only shows when at least one flag is here.
              Covers both "new" and any "revived" chips that landed back in Ignore. */}
          {(() => {
            const flaggedHere = tier.dimensionKeys.filter((k) => props.newKeys.has(k));
            return tier.ignore && flaggedHere.length > 0 ? (
              <div className="tier-mark-reviewed-row">
                <button
                  type="button"
                  className="tier-mark-reviewed"
                  onClick={() => props.onAcknowledge(flaggedHere)}
                >
                  <Check size={13} />
                  Clear all {flaggedHere.length} flag{flaggedHere.length === 1 ? "" : "s"}
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
  revivedKeys: Set<string>;
  favourited: Set<string>;
  openKey: string | null;
  // "Add criterion" toggle + its composer, owned by the parent. Rendered here so the
  // two "+ Add" actions (criterion / tier) sit together above the chips they act on.
  addOpen: boolean;
  onToggleAdd: () => void;
  composer: ReactNode;
  onAcknowledge: (keys: string[]) => void;
  onChange: (next: Tier[]) => void;
  onToggleFav: (key: string, favourited: boolean) => void;
  onOpen: (key: string) => void;
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
    const key = String(event.active.id);
    setActiveKey(key);
    // Picking a chip up also shows its description (drag and read aren't separate
    // actions). onOpen just sets the selection, so this is safe to fire every time.
    props.onOpen(key);
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
  const activeFav = activeKey ? props.favourited.has(activeKey) : false;

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
        <div className="tier-list-actions no-print">
          <button
            type="button"
            className="secondary-button tier-add"
            aria-expanded={props.addOpen}
            onClick={props.onToggleAdd}
          >
            <Plus size={14} /> Add criterion
          </button>
          <button type="button" className="secondary-button tier-add" onClick={addTier}>
            <Plus size={14} /> Add tier
          </button>
        </div>
      </div>
      {props.addOpen ? props.composer : null}
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
            revivedKeys={props.revivedKeys}
            favourited={props.favourited}
            openKey={props.openKey}
            isOver={overTierId === tier.id}
            canMoveUp={idx > 0}
            canMoveDown={idx < working.length - 1}
            onMoveUp={() => moveTier(idx, -1)}
            onMoveDown={() => moveTier(idx, 1)}
            onRemove={() => removeTier(tier.id)}
            onRename={(label) => renameTier(tier.id, label)}
            onAcknowledge={props.onAcknowledge}
            onToggleFav={props.onToggleFav}
            onOpen={props.onOpen}
          />
        ))}
        {ignore ? (
          <TierRow
            tier={ignore}
            labelFor={props.labelFor}
            newKeys={props.newKeys}
            revivedKeys={props.revivedKeys}
            favourited={props.favourited}
            openKey={props.openKey}
            isOver={overTierId === ignore.id}
            canMoveUp={false}
            canMoveDown={false}
            onMoveUp={() => {}}
            onMoveDown={() => {}}
            onRemove={() => {}}
            onRename={() => {}}
            onAcknowledge={props.onAcknowledge}
            onToggleFav={props.onToggleFav}
            onOpen={props.onOpen}
          />
        ) : null}
        {/* The floating copy that follows the cursor freely across tiers — this
            is what makes cross-tier drag smooth instead of clipped to a row. */}
        <DragOverlay>
          {activeLabel ? <ChipBody label={activeLabel} dragging isFav={activeFav} /> : null}
        </DragOverlay>
      </DndContext>
    </div>
  );
}
