"""Shared output formatting and the v0.5 token-sparse output budget.

Every MCP tool output funnels through the helpers in this module, which
enforce the v0.5 contract invariants (see ``Docs/V0.5/01-V0.5-CONTRACT.md``
binding clarifications and ``Docs/V0.5/05-V0.5-DECISIONS.md``):

- ``NORMAL_OUTPUT_CHARS`` (4000) is the target presentation budget for a
  default call (D001);
- ``MAX_OUTPUT_CHARS`` (16000) is the ABSOLUTE response ceiling and is
  never exceeded (D002);
- ``LINE_CLIP_CHARS`` (200) bounds every emitted line (D007);
- emission is atomic: a complete item is either emitted whole or not at all;
- truncation is explicit via ``OutputBudget.truncated`` / ``.omitted`` and
  the trailing ``[OUTPUT TRUNCATED: N characters omitted]`` marker.

The public ``truncate()`` and ``numbered_lines()`` entry points keep their
existing signatures so every existing call site keeps working; their
truncation boundary moves to a complete-line boundary and the 16,000-char
ceiling becomes the hard cap.

Phase B adds ``read_window_block()``, the windowed-read renderer behind
``mcquest_read_file`` / ``mcquest_read_doc``: a summary-first page with
``total_lines`` / ``next_start_line`` / ``has_more`` / ``truncated`` under
the asymmetric read budgets (D004/D010).

Phase C adds ``discovery_block()``, the summary-first discovery-page
renderer behind ``mcquest_list_files`` / ``mcquest_list_docs`` /
``mcquest_find_files``: a ``[SUMMARY]`` block (``total`` / ``COUNT`` /
``returned`` / ``offset`` / ``next_offset`` / ``has_more`` / ``truncated`` /
``collection_complete`` / ``budget``) followed by the evidence body with
explicit ``offset`` continuation (D008) and deterministic ordering (D009).

Phase D adds ``search_block()``, the summary-first search/evidence-page
renderer behind ``mcquest_search`` / ``mcquest_search_docs`` /
``mcquest_find_imports`` / ``mcquest_find_usages`` / ``mcquest_find_evidence``
and the ``phase_context`` query mode. Unlike ``discovery_block`` (whose items
are single-line paths), each item is a structured multi-line snippet: every
emitted line of an item is clipped at ``LINE_CLIP_CHARS`` while the internal
newline structure is preserved, and the complete item is emitted atomically so
an over-budget snippet is dropped whole rather than split (D007/D016).
"""

from __future__ import annotations

from .config import LINE_CLIP_CHARS, MAX_OUTPUT_CHARS, NORMAL_OUTPUT_CHARS


def _clip_line(line: str, limit: int = LINE_CLIP_CHARS) -> str:
    """Clip ``line`` to at most ``limit`` characters.

    Overlong lines keep their first ``limit - 1`` characters followed by an
    ellipsis, mirroring the existing ``diagnostics._clip`` precedent so the
    200-char bound is applied consistently across all output paths.
    """
    if len(line) <= limit:
        return line
    return line[: limit - 1] + "…"


class OutputBudget:
    """Track emitted characters against the v0.5 output budgets.

    ``normal`` (4000) is the target presentation budget for a default call;
    ``ceiling`` (16000) is an absolute bound that is never exceeded; ``clip``
    (200) bounds any single emitted line (prefix included).

    Emission is atomic: ``emit()`` / ``add_clipped_line()`` either accept the
    complete item or reject it whole (never a partial item). When an item is
    dropped because it would cross the ceiling, ``truncated`` flips to ``True``
    and the caller should stop adding evidence. A header registered with
    ``add_header()`` is emitted first in ``finalize()`` and therefore survives
    truncation; ``finalize()`` always stays within the ceiling.
    """

    def __init__(
        self,
        normal: int = NORMAL_OUTPUT_CHARS,
        ceiling: int = MAX_OUTPUT_CHARS,
        clip: int = LINE_CLIP_CHARS,
    ) -> None:
        self.normal = normal
        self.ceiling = ceiling
        self.clip = clip
        self._header: list[str] = []
        self._parts: list[str] = []
        self._used = 0
        self._omitted = 0
        self._truncated = False

    # -- state --------------------------------------------------------

    @property
    def used(self) -> int:
        """Characters currently committed to the output body."""
        return self._used

    @property
    def omitted(self) -> int:
        """Input characters dropped so far (clipped or rejected)."""
        return self._omitted

    @property
    def truncated(self) -> bool:
        """True when at least one input character was dropped."""
        return self._truncated

    @property
    def remaining(self) -> int:
        """Characters still available under the absolute ceiling."""
        return self.ceiling - self._used

    # -- emission -----------------------------------------------------

    def fits(self, item: str) -> bool:
        """Return True when the complete ``item`` fits under the ceiling."""
        return self._used + len(item) <= self.ceiling

    def emit(self, item: str) -> bool:
        """Emit ``item`` atomically.

        Returns False (and marks truncation) when the complete item cannot
        fit under the ceiling; the item is then dropped whole.
        """
        if not item:
            return True
        if not self.fits(item):
            self._truncated = True
            self._omitted += len(item)
            return False
        self._parts.append(item)
        self._used += len(item)
        return True

    def add_clipped_line(self, line: str) -> bool:
        """Clip ``line`` to the per-line limit, then emit it atomically."""
        clipped = _clip_line(line, self.clip)
        if len(clipped) != len(line):
            self._truncated = True
            self._omitted += len(line) - len(clipped)
        return self.emit(clipped)

    def add_header(self, header: str) -> "OutputBudget":
        """Register a header emitted before the body.

        The header counts toward the ceiling and always survives truncation,
        so callers should add it before the evidence items.
        """
        self._header.append(header)
        return self

    def mark_truncated(self, omitted_chars: int = 0) -> "OutputBudget":
        """Record dropped content without emitting an item.

        Callers that stop at an exact presentation boundary (e.g. read
        windows decided by ``read_window_block``) use this to set the
        truncated state and omitted-character count so ``finalize()`` emits
        the ``[OUTPUT TRUNCATED: N characters omitted]`` marker with the
        correct N. Additive to the Phase A surface; the ceiling is still
        enforced by ``finalize()``.
        """
        self._truncated = True
        if omitted_chars > 0:
            self._omitted += omitted_chars
        return self

    # -- output -------------------------------------------------------

    def finalize(self) -> str:
        """Render the header + body, appending the truncation marker when
        characters were dropped, and never exceeding the ceiling."""
        header = "\n\n".join(self._header)
        body = "\n".join(self._parts)

        if header and body:
            text = f"{header}\n\n{body}"
        else:
            text = header or body

        if not self._truncated:
            return text

        marker = f"\n\n[OUTPUT TRUNCATED: {self._omitted:,} characters omitted]"

        # The ceiling is absolute: drop whole emitted items (never partial
        # ones) from the tail until the marker fits.
        while self._parts and len(text) + len(marker) > self.ceiling:
            item = self._parts.pop()
            self._used -= len(item)
            self._omitted += len(item)
            body = "\n".join(self._parts)
            text = f"{header}\n\n{body}" if header and body else (header or body)

        return text + marker


def truncate(text: str, limit: int = MAX_OUTPUT_CHARS) -> str:
    """Bound ``text`` to the v0.5 absolute ceiling.

    The public signature is preserved for compatibility with every existing
    call site. Lines are clipped at ``LINE_CLIP_CHARS`` and the output ends
    on a complete line; a ``[OUTPUT TRUNCATED: N characters omitted]`` marker
    is appended whenever any character was dropped. The result never exceeds
    ``limit`` characters.
    """
    budget = OutputBudget(ceiling=limit)
    for line in text.splitlines():
        if not budget.add_clipped_line(line):
            break
    return budget.finalize()


def numbered_lines(
    text: str,
    start_line: int = 1,
    end_line: int | None = None,
    limit: int = MAX_OUTPUT_CHARS,
) -> str:
    """Number each selected line with its existing ``INDEX: `` prefix.

    Each emitted line (prefix included) is clipped at ``LINE_CLIP_CHARS``,
    emission is atomic per line, and the result never exceeds ``limit``
    characters. Long lines are clipped but the numbering remains exact.
    """
    lines = text.splitlines()

    start_index = max(start_line - 1, 0)

    if end_line is None:
        selected = lines[start_index:]
    else:
        selected = lines[start_index:end_line]

    budget = OutputBudget(ceiling=limit)

    for index, line in enumerate(selected, start=start_index + 1):
        if not budget.add_clipped_line(f"{index:6}: {line}"):
            break

    return budget.finalize()


def summary_block(
    tool: str,
    fields: dict[str, object],
    scope: str = "",
) -> str:
    """Render the canonical v0.5 ``[SUMMARY]`` header.

    Later phases emit this block first (through ``OutputBudget.add_header`` so
    it survives truncation), then the evidence body, then a final ``[END]``
    line:

        [SUMMARY]
        tool: <tool>
        scope: <scope>          # optional
        <key>: <value>          # for each field
        [EVIDENCE]
    """
    lines = ["[SUMMARY]", f"tool: {tool}"]
    if scope:
        lines.append(f"scope: {scope}")
    for key, value in fields.items():
        lines.append(f"{key}: {value}")
    lines.append("[EVIDENCE]")
    return "\n".join(lines)


# Phase B read-window constants (decision D010: default window 250 lines,
# explicit-range hard window 1,000 lines).
DEFAULT_READ_WINDOW_LINES = 250
MAX_READ_WINDOW_LINES = 1_000


def read_window_block(
    tool: str,
    path: str,
    text: str,
    start_line: int = 1,
    end_line: int | None = None,
    normal: int = NORMAL_OUTPUT_CHARS,
    ceiling: int = MAX_OUTPUT_CHARS,
) -> str:
    """Render a windowed read under the v0.5 output budgets.

    Used by ``mcquest_read_file`` / ``mcquest_read_doc`` (decisions D004,
    D010). Semantics:

    - Default read (``start_line == 1``, ``end_line is None``): at most
      ``DEFAULT_READ_WINDOW_LINES`` (250) lines under the ``normal`` (4000)
      presentation budget.
    - Continuation (``start_line > 1``, ``end_line is None``): the next
      250-line window under the ``ceiling`` (16000) presentation budget
      (approved Phase B special case).
    - Explicit range (``end_line`` supplied): at most
      ``MAX_READ_WINDOW_LINES`` (1000) lines under the ``ceiling`` budget.
      Ranges beyond the end of the file are clamped; a start beyond the end
      of the file renders an empty page without error, preserving the
      previous ``numbered_lines`` behavior.

    The response is summary-first (the header is registered with
    ``OutputBudget.add_header`` so it survives truncation) using the
    canonical ``[SUMMARY]`` block: ``tool``, ``scope: path=\"...\"``,
    ``start_line``, ``end_line`` (the ACTUAL rendered end, ``0`` when
    nothing was rendered), ``total_lines``, optional ``next_start_line``
    (= rendered end_line + 1) when ``has_more``, ``has_more``,
    ``truncated``, and ``budget`` (``<presentation>/<ceiling>``).

    ``truncated`` is true whenever input characters were dropped, i.e. any
    rendered line was clipped at ``LINE_CLIP_CHARS`` OR the presentation
    budget cut the requested window — the exact Phase A ``OutputBudget``
    definition (never redefined here).

    Budget enforcement is exact: the item count that fits is computed from
    the full rendered length (summary + separators + body + trailer)
    BEFORE emission, guaranteeing ``finalize()`` never pops a rendered item
    and the summary's ``end_line``/``next_start_line`` always describe the
    actual page. All emission flows through ``OutputBudget`` (atomic items,
    per-line clip, truncation marker) — no budget logic is duplicated.
    """
    lines = text.splitlines()
    total = len(lines)

    effective_start = max(start_line, 1)

    if end_line is None:
        # A natural default read uses the normal budget; any continuation
        # request is explicit expansion (D004 + approved special case).
        presentation = normal if effective_start == 1 else ceiling
        raw_end = effective_start + DEFAULT_READ_WINDOW_LINES - 1
    else:
        presentation = ceiling
        raw_end = min(
            end_line,
            effective_start + MAX_READ_WINDOW_LINES - 1,
        )

    # 1-based inclusive window end, clamped to the end of the document.
    # ``requested_end < effective_start`` => empty page (e.g. start beyond
    # EOF, or end_line < start_line) mirroring the old numbered_lines slice.
    requested_end = min(max(raw_end, effective_start - 1), total)

    items = [
        f"{index:6}: {lines[index - 1]}"
        for index in range(effective_start, requested_end + 1)
    ]
    n = len(items)

    # Exact prefix accounting: clipped lengths, clip-dropped characters and
    # raw lengths (for the omitted count of a page cut).
    prefixes = [0] * (n + 1)
    drops = [0] * (n + 1)
    raw_prefixes = [0] * (n + 1)
    for i, item in enumerate(items, start=1):
        clipped = _clip_line(item, LINE_CLIP_CHARS)
        prefixes[i] = prefixes[i - 1] + len(clipped)
        drops[i] = drops[i - 1] + (len(item) - len(clipped))
        raw_prefixes[i] = raw_prefixes[i - 1] + len(item)

    def truncated_for(k: int) -> bool:
        return drops[k] > 0 or k < n

    def summary_for(k: int) -> str:
        rendered_end = effective_start + k - 1 if k else 0
        has_more = k > 0 and rendered_end < total
        fields: dict[str, object] = {
            "start_line": effective_start,
            "end_line": rendered_end,
            "total_lines": total,
        }
        if has_more:
            fields["next_start_line"] = rendered_end + 1
        fields["has_more"] = "true" if has_more else "false"
        fields["truncated"] = "true" if truncated_for(k) else "false"
        fields["budget"] = f"{presentation}/{ceiling}"
        return summary_block(tool, fields, scope=f'path="{path}"')

    def size_for(k: int) -> int:
        """Exact rendered length for the first ``k`` items.

        Mirrors ``OutputBudget.finalize()`` exactly: the summary header, the
        blank-line separator, the body joined by single newlines, and either
        the ``[END]`` trailer (not truncated) or the truncation marker whose
        omitted count covers every window character not rendered plus every
        clip-dropped character.
        """
        body = prefixes[k] + (k - 1 if k else 0)
        trunk = len(summary_for(k)) + 2 + body
        if truncated_for(k):
            omitted = drops[k] + (raw_prefixes[n] - raw_prefixes[k])
            marker = f"\n\n[OUTPUT TRUNCATED: {omitted:,} characters omitted]"
            return trunk + len(marker)
        return trunk + len("[END]") + (1 if k else 0)

    # Largest item count whose exact rendered length stays within the
    # presentation budget (monotone except for a possible settle at EOF).
    best = 0
    for k in range(n + 1):
        if size_for(k) <= presentation:
            best = k

    budget = OutputBudget(ceiling=presentation, clip=LINE_CLIP_CHARS)
    budget.add_header(summary_for(best))
    for item in items[:best]:
        if not budget.add_clipped_line(item):
            break
    if best < n:
        # The page is cut by the presentation budget: record every unrendered
        # window character (raw lengths) so the marker count is exact.
        budget.mark_truncated(raw_prefixes[n] - raw_prefixes[best])
    elif not truncated_for(best):
        budget.add_clipped_line("[END]")
    return budget.finalize()


# Phase C discovery-page renderer: ``discovery_block()`` (decisions D008,
# D009 + approved Phase C plan). Page-size constants live in config
# (DISCOVERY_DEFAULT_RESULTS / DISCOVERY_MAX_RESULTS).


def discovery_block(
    tool: str,
    path: str,
    items: list[str],
    total: int,
    offset: int = 0,
    fields: dict[str, object] | None = None,
    aggregates: str = "",
    normal: int = NORMAL_OUTPUT_CHARS,
    ceiling: int = MAX_OUTPUT_CHARS,
    expanded: bool = False,
) -> str:
    """Render a summary-first discovery page under the v0.5 output budgets.

    Used by ``mcquest_list_files`` / ``mcquest_list_docs`` /
    ``mcquest_find_files`` (decisions D008, D009; Phase C). Semantics:

    - ``items`` is the deterministic, globally-ordered page slice for this
      ``offset`` (already bounded to the tool's hard cap by the caller).
    - ``total`` is the honest overall match count computed by a full
      counting pass, so ``collection_complete`` is always reported true.
    - Budget asymmetry (D004, applied to discovery pages): a default page
      (``expanded=False``) uses the ``normal`` (4000) presentation budget;
      an explicitly expanded page (``expanded=True``, e.g. ``offset > 0``
      continuation or ``max_results`` beyond the default page size) may use
      up to the ``ceiling`` (16000). The absolute ceiling is never exceeded.
    - The response is summary-first using the canonical ``[SUMMARY]`` block:
      ``tool``, ``scope: path=\\\"...\\\"``, caller ``fields`` (e.g. pattern /
      query), the legacy ``COUNT`` line (= returned), ``total``, ``returned``,
      ``offset``, optional ``next_offset`` (= offset + returned) when
      ``has_more``, ``has_more``, ``truncated``, ``collection_complete``,
      ``budget`` (``<presentation>/<ceiling>``), and optional ``aggregate``
      metadata. The header is registered with ``OutputBudget.add_header`` so
      it survives truncation.
    - ``truncated`` is true when the presentation budget cut the page
      (``best < len(items)``) or any item line was clipped at
      ``LINE_CLIP_CHARS``.
    - ``next_offset`` = ``offset + returned`` only when ``has_more``; page 2
      is never emitted automatically (D008).

    Budget enforcement is exact (the same ``size_for`` accounting used by
    ``read_window_block``): the returned count is computed from the full
    rendered length BEFORE emission so ``finalize()`` never pops an item and
    the summary ``returned``/``next_offset`` describe the actual page. All
    emission flows through ``OutputBudget`` (atomic items, per-line clip,
    truncation marker) -- no budget logic is duplicated.
    """
    presentation = ceiling if expanded else normal
    n = len(items)

    # Exact prefix accounting: clipped lengths, clip-dropped characters and
    # raw lengths (for the omitted count of a page cut).
    prefixes = [0] * (n + 1)
    drops = [0] * (n + 1)
    raw_prefixes = [0] * (n + 1)
    for i, item in enumerate(items, start=1):
        clipped = _clip_line(item, LINE_CLIP_CHARS)
        prefixes[i] = prefixes[i - 1] + len(clipped)
        drops[i] = drops[i - 1] + (len(item) - len(clipped))
        raw_prefixes[i] = raw_prefixes[i - 1] + len(item)

    def truncated_for(k: int) -> bool:
        return drops[k] > 0 or k < n

    def summary_for(k: int) -> str:
        has_more = (offset + k) < total
        fields_: dict[str, object] = {
            "COUNT": k,
            "total": total,
            "returned": k,
            "offset": offset,
        }
        if has_more:
            fields_["next_offset"] = offset + k
        fields_["has_more"] = "true" if has_more else "false"
        fields_["truncated"] = "true" if truncated_for(k) else "false"
        fields_["collection_complete"] = "true"
        fields_["budget"] = f"{presentation}/{ceiling}"
        if aggregates:
            fields_["aggregate"] = aggregates
        merged: dict[str, object] = {}
        if fields:
            merged.update(fields)
        merged.update(fields_)
        return summary_block(tool, merged, scope=f'path="{path}"')

    def size_for(k: int) -> int:
        """Exact rendered length for the first ``k`` items.

        Mirrors ``OutputBudget.finalize()`` exactly: the summary header, the
        blank-line separator, the body joined by single newlines, and either
        the ``[END]`` trailer (not truncated) or the truncation marker whose
        omitted count covers every unrendered item (raw lengths) plus every
        clip-dropped character.
        """
        body = prefixes[k] + (k - 1 if k else 0)
        trunk = len(summary_for(k)) + 2 + body
        if truncated_for(k):
            omitted = drops[k] + (raw_prefixes[n] - raw_prefixes[k])
            marker = f"\n\n[OUTPUT TRUNCATED: {omitted:,} characters omitted]"
            return trunk + len(marker)
        return trunk + len("[END]") + (1 if k else 0)

    # Largest item count whose exact rendered length stays within the
    # presentation budget (monotone except for a possible settle at total).
    best = 0
    for k in range(n + 1):
        if size_for(k) <= presentation:
            best = k

    budget = OutputBudget(ceiling=presentation, clip=LINE_CLIP_CHARS)
    budget.add_header(summary_for(best))
    for item in items[:best]:
        if not budget.add_clipped_line(item):
            break
    if best < n:
        # The page is cut by the presentation budget: record every unrendered
        # item's raw length so the marker count is exact.
        budget.mark_truncated(raw_prefixes[n] - raw_prefixes[best])
    elif not truncated_for(best):
        budget.add_clipped_line("[END]")
    return budget.finalize()


# Phase D search/evidence-page renderer: ``search_block()`` (decisions D016 +
# approved Phase D plan). Unlike ``discovery_block``, every item is a
# structured multi-line snippet (matching lines plus context): each line of an
# item is clipped at LINE_CLIP_CHARS while the snippet keeps its internal
# newline structure, and the complete snippet is emitted atomically.


def search_block(
    tool: str,
    path: str,
    items: list[str],
    total: int,
    files_affected: int,
    offset: int = 0,
    fields: dict[str, object] | None = None,
    scope: str = "",
    normal: int = NORMAL_OUTPUT_CHARS,
    ceiling: int = MAX_OUTPUT_CHARS,
    expanded: bool = False,
) -> str:
    """Render a summary-first search/evidence page under the v0.5 budgets.

    Used by ``mcquest_search`` / ``mcquest_search_docs`` /
    ``mcquest_find_imports`` / ``mcquest_find_usages`` /
    ``mcquest_find_evidence`` and the ``phase_context`` query mode (decisions
    D001/D002/D004/D007/D008/D009/D016).

    Each ``item`` is a multi-line snippet (e.g. ``path:line`` plus context).
    During accounting and emission every line of the item is clipped at
    ``LINE_CLIP_CHARS`` while the item's internal newline structure is
    preserved, and the complete rendered item is emitted atomically: an
    over-budget snippet is dropped whole, never split mid-line or mid-snippet.
    """
    presentation = ceiling if expanded else normal
    n = len(items)

    # Per-line clipping preserves each snippet's internal newline structure:
    # rendered_items[i] is item i with every line clipped at LINE_CLIP_CHARS.
    rendered_items: list[tuple[str, int]] = []
    for item in items:
        lines = item.split("\n")
        clipped = [_clip_line(line, LINE_CLIP_CHARS) for line in lines]
        dropped = sum(len(a) - len(b) for a, b in zip(lines, clipped))
        rendered_items.append(("\n".join(clipped), dropped))

    prefixes = [0] * (n + 1)
    drops = [0] * (n + 1)
    raw_prefixes = [0] * (n + 1)
    for i, (rendered, dropped) in enumerate(rendered_items, start=1):
        prefixes[i] = prefixes[i - 1] + len(rendered)
        drops[i] = drops[i - 1] + dropped
        raw_prefixes[i] = raw_prefixes[i - 1] + len(items[i - 1])

    def truncated_for(k: int) -> bool:
        return drops[k] > 0 or k < n

    def summary_for(k: int) -> str:
        has_more = (offset + k) < total
        fields_: dict[str, object] = {
            "total": total,
            "files_affected": files_affected,
            "returned": k,
            "offset": offset,
        }
        if has_more:
            fields_["next_offset"] = offset + k
        fields_["has_more"] = "true" if has_more else "false"
        fields_["truncated"] = "true" if truncated_for(k) else "false"
        fields_["collection_complete"] = "true"
        fields_["budget"] = f"{presentation}/{ceiling}"
        merged: dict[str, object] = {}
        if fields:
            merged.update(fields)
        merged.update(fields_)
        return summary_block(tool, merged, scope=scope or f'path="{path}"')

    def size_for(k: int) -> int:
        """Exact rendered length for the first ``k`` items.

        Mirrors ``OutputBudget.finalize()`` exactly: the summary header, the
        blank-line separator, the body (clipped snippets joined by single
        newlines), and either the ``[END]`` trailer (not truncated) or the
        truncation marker whose omitted count covers every raw snippet
        character not rendered plus every clip-dropped character.
        """
        body = prefixes[k] + (k - 1 if k else 0)
        trunk = len(summary_for(k)) + 2 + body
        if truncated_for(k):
            omitted = drops[k] + (raw_prefixes[n] - raw_prefixes[k])
            marker = f"\n\n[OUTPUT TRUNCATED: {omitted:,} characters omitted]"
            return trunk + len(marker)
        return trunk + len("[END]") + (1 if k else 0)

    # Largest item count whose exact rendered length stays within the
    # presentation budget (monotone except for a possible settle at total).
    best = 0
    for k in range(n + 1):
        if size_for(k) <= presentation:
            best = k

    budget = OutputBudget(ceiling=presentation, clip=LINE_CLIP_CHARS)
    budget.add_header(summary_for(best))
    for rendered, _ in rendered_items[:best]:
        if not budget.emit(rendered):
            break
    if best < n:
        # Page cut by the presentation budget: every clip drop from rendered
        # items plus every raw character of unrendered snippets.
        budget.mark_truncated(drops[best] + (raw_prefixes[n] - raw_prefixes[best]))
    elif drops[best] > 0:
        # Every snippet rendered but at least one line was clipped.
        budget.mark_truncated(drops[best])
    else:
        budget.emit("[END]")
    return budget.finalize()


# Phase 1 (v0.6 E1 carry-forward) pattern-audit renderer: ``audit_block()``.
# Summary-first over the v0.5 budgets for the ``pattern_audit`` tool: a
# ``[SUMMARY]`` header (category_count, matches, samples_shown, has_more,
# truncated, collection_complete, budget) plus a ``[CATEGORY COUNTS]`` block
# that always survives truncation, then per-category bounded sample blocks.
# ``has_more`` signals collected matches beyond the displayed sample lines;
# ``truncated`` signals a presentation-budget cut or clipped lines. The
# single-category ``category`` parameter is the explicit expansion path.


def audit_block(
    tool: str,
    path: str,
    categories: list[str],
    counts: list[int],
    samples: list[list[str]],
    fields: dict[str, object] | None = None,
    scope: str = "",
    normal: int = NORMAL_OUTPUT_CHARS,
    ceiling: int = MAX_OUTPUT_CHARS,
    expanded: bool = False,
) -> str:
    """Render a summary-first pattern-audit page under the v0.5 budgets.

    ``categories`` / ``counts`` / ``samples`` are parallel lists in
    deterministic category order. ``counts[i]`` is the collected match total
    for category ``i`` and ``samples[i]`` the match lines to display for it
    (a bounded written subset). A default call (``expanded=False``) uses the
    ``normal`` (4000) presentation budget; an explicit expansion
    (``expanded=True``, e.g. a single-category ``category`` request or an
    enlarged ``max_results_per_category``) may use up to the ``ceiling``
    (16000).
    """
    presentation = ceiling if expanded else normal
    n = len(categories)
    assert n == len(counts) == len(samples)

    total_matches = sum(counts)
    block_indices = [i for i in range(n) if samples[i]]
    m = len(block_indices)

    # Exact accounting over the deterministic sample blocks: rendered lengths,
    # clip-dropped characters, raw (unclipped) lengths, and displayed-sample
    # counts, so the fitted row count and every metadata field are exact.
    rendered_block: list[str] = []
    block_drop: list[int] = []
    rendered_prefix = [0] * (m + 1)
    drop_prefix = [0] * (m + 1)
    raw_prefix = [0] * (m + 1)
    for j, i in enumerate(block_indices, start=1):
        raw_lines = samples[i]
        clipped = [_clip_line(line, LINE_CLIP_CHARS) for line in raw_lines]
        rendered = "## {}\n{}".format(categories[i], "\n".join(clipped))
        raw_block = "## {}\n{}".format(categories[i], "\n".join(raw_lines))
        rendered_block.append(rendered)
        block_drop.append(len(raw_block) - len(rendered))
        rendered_prefix[j] = rendered_prefix[j - 1] + len(rendered)
        drop_prefix[j] = drop_prefix[j - 1] + block_drop[-1]
        raw_prefix[j] = raw_prefix[j - 1] + len(raw_block)

    shown_prefix = [0] * (m + 1)
    for j, i in enumerate(block_indices, start=1):
        shown_prefix[j] = shown_prefix[j - 1] + len(samples[i])

    counts_block = "[CATEGORY COUNTS]\n" + "\n".join(
        f"{name}: {count}" for name, count in zip(categories, counts)
    )

    def truncated_for(k: int) -> bool:
        return drop_prefix[k] > 0 or k < m

    def has_more_for(k: int) -> bool:
        return total_matches > shown_prefix[k]

    def summary_for(k: int) -> str:
        fields_: dict[str, object] = {
            "category_count": n,
            "matches": total_matches,
            "samples_shown": shown_prefix[k],
            "has_more": "true" if has_more_for(k) else "false",
            "truncated": "true" if truncated_for(k) else "false",
            "collection_complete": "true",
            "budget": f"{presentation}/{ceiling}",
        }
        merged: dict[str, object] = {}
        if fields:
            merged.update(fields)
        merged.update(fields_)
        return summary_block(tool, merged, scope=scope or f'path="{path}"')

    def size_for(k: int) -> int:
        """Exact rendered length for the first ``k`` sample blocks.

        Mirrors ``OutputBudget.finalize()`` exactly: the summary header, the
        ``[CATEGORY COUNTS]`` block, the body (sample blocks joined by single
        newlines), and either the ``[END]`` trailer (not truncated) or the
        truncation marker whose omitted count covers every unrendered block
        (raw lengths) plus every clip-dropped character of rendered blocks.
        """
        body = rendered_prefix[k] + (k - 1 if k else 0)
        header = summary_for(k) + "\n\n" + counts_block
        trunk = len(header) + 2 + body
        if truncated_for(k):
            omitted = drop_prefix[k] + (raw_prefix[m] - raw_prefix[k])
            marker = f"\n\n[OUTPUT TRUNCATED: {omitted:,} characters omitted]"
            return trunk + len(marker)
        return trunk + len("[END]") + (1 if k else 0)

    # Largest sample-block count whose exact rendered length stays within the
    # presentation budget (monotone except for a possible settle at m).
    best = 0
    for k in range(m + 1):
        if size_for(k) <= presentation:
            best = k

    budget = OutputBudget(ceiling=presentation, clip=LINE_CLIP_CHARS)
    budget.add_header(summary_for(best) + "\n\n" + counts_block)
    for rendered in rendered_block[:best]:
        if not budget.emit(rendered):
            break
    if best < m:
        # Page cut by the presentation budget: every clip drop from rendered
        # blocks plus every raw character of unrendered sample blocks.
        budget.mark_truncated(drop_prefix[best] + (raw_prefix[m] - raw_prefix[best]))
    elif drop_prefix[best] > 0:
        # Every block rendered but at least one sample line was clipped.
        budget.mark_truncated(drop_prefix[best])
    else:
        budget.emit("[END]")
    return budget.finalize()