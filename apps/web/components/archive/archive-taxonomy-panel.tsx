import type { CSSProperties, ReactNode } from "react";

const joinClasses = (...values: Array<string | false | null | undefined>) =>
  values.filter(Boolean).join(" ");

type ArchiveTaxonomyLensOption = {
  active?: boolean;
  id: string;
  label: string;
};

type ArchiveTaxonomySearchControl = {
  ariaLabel?: string;
  id?: string;
  onChange: (value: string) => void;
  placeholder: string;
  type?: "search" | "text";
  value: string;
};

type ArchiveTaxonomyThresholdControl = {
  canDecrease: boolean;
  canIncrease: boolean;
  containerId?: string;
  decreaseLabel?: string;
  increaseLabel?: string;
  onDecrease: () => void;
  onIncrease: () => void;
  valueLabel: string;
};

type ArchiveTaxonomyFilterOption = {
  active: boolean;
  id: string;
  label: string;
  onSelect: () => void;
};

type ArchiveTaxonomySortControl = {
  ariaLabel?: string;
  id?: string;
  onChange: (value: string) => void;
  options: Array<{
    label: string;
    value: string;
  }>;
  value: string;
};

export function ArchiveTaxonomyPanel({
  children,
  className,
  confidenceContainerId,
  confidenceFilters,
  lensOptions,
  lensTabsId,
  onLensChange,
  pager,
  rowsClassName,
  rowsId,
  search,
  sort,
  style,
  summary,
  threshold,
  title,
  titleId,
}: {
  children: ReactNode;
  className?: string;
  confidenceContainerId?: string;
  confidenceFilters?: ArchiveTaxonomyFilterOption[];
  lensOptions: ArchiveTaxonomyLensOption[];
  lensTabsId?: string;
  onLensChange: (lensId: string) => void;
  pager?: ReactNode;
  rowsClassName?: string;
  rowsId?: string;
  search: ArchiveTaxonomySearchControl;
  sort: ArchiveTaxonomySortControl;
  style?: CSSProperties;
  summary?: ReactNode;
  threshold?: ArchiveTaxonomyThresholdControl | null;
  title: ReactNode;
  titleId?: string;
}) {
  return (
    <div className={joinClasses(className ?? "taxonomy-panel")} style={style}>
      <div className="panel-head taxonomy-head">
        <h3 className="panel-title" id={titleId}>
          {title}
        </h3>
        {lensOptions.length ? (
          <div className="lens-tabs" id={lensTabsId}>
            {lensOptions.map((lens) => (
              <button
                className={joinClasses("chip-btn", lens.active && "active")}
                key={lens.id}
                onClick={() => onLensChange(lens.id)}
                type="button"
              >
                {lens.label}
              </button>
            ))}
          </div>
        ) : null}
      </div>

      {summary ? <p className="panel-copy">{summary}</p> : null}

      <div className="taxonomy-controls-bar">
        <div className="control taxonomy-search-control">
          <span className="mobile-search-shell mobile-search-shell-compact">
            <input
              aria-label={search.ariaLabel}
              className="taxonomy-field taxonomy-fine-field"
              id={search.id}
              onChange={(event) => search.onChange(event.target.value)}
              placeholder={search.placeholder}
              type={search.type ?? "text"}
              value={search.value}
            />
          </span>
        </div>
        <div className="taxonomy-controls-row">
          {threshold ? (
            <div className="pill-row" id={threshold.containerId}>
              <div className="threshold-stepper">
                <button
                  aria-label={threshold.decreaseLabel}
                  className="chip-btn taxonomy-fine-btn threshold-arrow"
                  disabled={!threshold.canDecrease}
                  onClick={threshold.onDecrease}
                  type="button"
                >
                  ▼
                </button>
                <span className="chip-btn taxonomy-fine-btn threshold-value">{threshold.valueLabel}</span>
                <button
                  aria-label={threshold.increaseLabel}
                  className="chip-btn taxonomy-fine-btn threshold-arrow"
                  disabled={!threshold.canIncrease}
                  onClick={threshold.onIncrease}
                  type="button"
                >
                  ▲
                </button>
              </div>
            </div>
          ) : null}

          {confidenceFilters?.length ? (
            <div className="pill-row" id={confidenceContainerId}>
              {confidenceFilters.map((filter) => (
                <button
                  className={joinClasses("chip-btn", "taxonomy-fine-btn", filter.active && "active")}
                  key={filter.id}
                  onClick={filter.onSelect}
                  type="button"
                >
                  {filter.label}
                </button>
              ))}
            </div>
          ) : null}

          <div className="control taxonomy-sort-control">
            <span aria-hidden="true" className="taxonomy-sort-icon">
              ↕
            </span>
            <select
              aria-label={sort.ariaLabel}
              className="taxonomy-field taxonomy-fine-field taxonomy-select-field"
              id={sort.id}
              onChange={(event) => sort.onChange(event.target.value)}
              value={sort.value}
            >
              {sort.options.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </div>
        </div>
      </div>

      <div className={joinClasses(rowsClassName ?? "rows")} id={rowsId}>
        {children}
      </div>
      {pager}
    </div>
  );
}
