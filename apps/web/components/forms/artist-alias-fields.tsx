"use client";

import { useState } from "react";

import { maxArtistAliases } from "@/lib/jobs/artist-aliases";

import styles from "./artist-alias-fields.module.css";

type ArtistAliasFieldsProps = {
  className?: string;
  inputClassName?: string;
  name?: string;
  values: string[];
  onChange: (values: string[]) => void;
};

const joinClasses = (...classes: Array<string | false | null | undefined>) =>
  classes.filter(Boolean).join(" ");

export function ArtistAliasFields({
  className,
  inputClassName,
  name,
  values,
  onChange,
}: ArtistAliasFieldsProps) {
  const [isExpanded, setIsExpanded] = useState(false);

  const toggleExpanded = () => {
    setIsExpanded((current) => {
      const next = !current;
      if (next && values.length === 0) {
        onChange([""]);
      }
      return next;
    });
  };

  const updateAt = (index: number, nextValue: string) => {
    onChange(values.map((value, currentIndex) => (currentIndex === index ? nextValue : value)));
  };

  const addAlias = () => {
    if (values.length >= maxArtistAliases) {
      return;
    }

    onChange([...values, ""]);
  };

  const removeAlias = (index: number) => {
    onChange(values.filter((_, currentIndex) => currentIndex !== index));
  };

  const toggleLabel = isExpanded ? "Hide aliases" : "+ Alias";

  return (
    <div className={joinClasses(styles.root, className)}>
      <button className={styles.toggle} onClick={toggleExpanded} type="button">
        {toggleLabel}
      </button>

      {isExpanded ? (
        <div className={styles.rows}>
          {(values.length > 0 ? values : [""]).map((value, index, rows) => {
            const showAddAlias = index === rows.length - 1 && rows.length < maxArtistAliases;
            const showRemove = rows.length > 1;

            return (
              <div className={styles.row} key={`artist-alias-${index}`}>
                <div className={styles.inputWrap}>
                  <input
                    className={joinClasses(styles.input, inputClassName)}
                    name={name}
                    onChange={(event) => updateAt(index, event.target.value)}
                    placeholder="Alternate artist name"
                    type="text"
                    value={value}
                  />
                </div>
                <div className={styles.actions}>
                  {showAddAlias ? (
                    <button className={styles.action} onClick={addAlias} type="button">
                      + Alias
                    </button>
                  ) : null}
                  {showRemove ? (
                    <button className={styles.action} onClick={() => removeAlias(index)} type="button">
                      Remove
                    </button>
                  ) : null}
                </div>
              </div>
            );
          })}
          <p className={styles.hint}>Optional. Add up to {maxArtistAliases} alternate names used in set titles.</p>
        </div>
      ) : null}
    </div>
  );
}
