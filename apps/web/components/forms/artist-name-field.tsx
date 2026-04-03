"use client";

import { useEffect, useId, useMemo, useRef, useState } from "react";

import styles from "./artist-name-field.module.css";

type ArtistSuggestion = {
  id: string;
  slug: string;
  name: string;
  setCount: number;
};

type ArtistNameFieldProps = {
  className?: string;
  disabled?: boolean;
  existingArtistHelperText?: string;
  inputClassName?: string;
  name?: string;
  onSuggestionSelect?: (artist: ArtistSuggestion) => void;
  onValueChange?: (value: string) => void;
  placeholder?: string;
  required?: boolean;
  value?: string;
};

const joinClasses = (...classes: Array<string | false | null | undefined>) =>
  classes.filter(Boolean).join(" ");

export function ArtistNameField({
  className,
  disabled = false,
  existingArtistHelperText = "Select an existing artist to add additional sets to their existing page",
  inputClassName,
  name,
  onSuggestionSelect,
  onValueChange,
  placeholder,
  required = false,
  value,
}: ArtistNameFieldProps) {
  const isControlled = value !== undefined;
  const [internalValue, setInternalValue] = useState("");
  const [hasFocus, setHasFocus] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [suggestions, setSuggestions] = useState<ArtistSuggestion[]>([]);
  const inputRef = useRef<HTMLInputElement | null>(null);
  const listId = useId();

  const inputValue = isControlled ? value : internalValue;
  const trimmedValue = inputValue.trim();

  const setValue = (nextValue: string) => {
    if (!isControlled) {
      setInternalValue(nextValue);
    }
    onValueChange?.(nextValue);
  };

  useEffect(() => {
    if (!trimmedValue) {
      setSuggestions([]);
      setIsLoading(false);
      return;
    }

    const controller = new AbortController();
    const timeoutId = window.setTimeout(async () => {
      setIsLoading(true);

      try {
        const response = await fetch(`/api/artists/suggestions?q=${encodeURIComponent(trimmedValue)}`, {
          signal: controller.signal,
        });

        if (!response.ok) {
          throw new Error(`HTTP ${response.status}`);
        }

        const data = (await response.json()) as { artists?: ArtistSuggestion[] };
        setSuggestions(Array.isArray(data.artists) ? data.artists : []);
      } catch {
        if (!controller.signal.aborted) {
          setSuggestions([]);
        }
      } finally {
        if (!controller.signal.aborted) {
          setIsLoading(false);
        }
      }
    }, 120);

    return () => {
      controller.abort();
      window.clearTimeout(timeoutId);
    };
  }, [trimmedValue]);

  const showDropdown = hasFocus && !!trimmedValue;
  const hasSuggestions = suggestions.length > 0;

  const helperText = useMemo(() => {
    if (!trimmedValue) {
      return null;
    }

    if (isLoading) {
      return "Checking existing artist pages…";
    }

    if (hasSuggestions) {
      return existingArtistHelperText;
    }

    return "No existing artist page starts with this prefix. Submitting will create a new artist page.";
  }, [existingArtistHelperText, hasSuggestions, isLoading, trimmedValue]);

  return (
    <div className={joinClasses(styles.root, className)}>
      <input
        ref={inputRef}
        aria-autocomplete="list"
        aria-controls={showDropdown ? listId : undefined}
        aria-expanded={showDropdown}
        aria-haspopup="listbox"
        autoComplete="off"
        className={inputClassName}
        data-has-value={trimmedValue ? "true" : "false"}
        disabled={disabled}
        name={name}
        onBlur={() => setHasFocus(false)}
        onChange={(event) => setValue(event.target.value)}
        onFocus={() => setHasFocus(true)}
        onKeyDown={(event) => {
          if (event.key === "Escape") {
            setHasFocus(false);
            inputRef.current?.blur();
          }
        }}
        placeholder={placeholder}
        required={required}
        role="combobox"
        spellCheck={false}
        type="text"
        value={inputValue}
      />

      {showDropdown ? (
        <div className={styles.dropdown} id={listId} onMouseDown={(event) => event.preventDefault()}>
          <div className={styles.heading}>Existing artist pages</div>
          {hasSuggestions ? (
            <ul className={styles.list} role="listbox">
              {suggestions.map((artist) => (
                <li key={artist.id}>
                  <button
                    aria-selected="false"
                    className={styles.option}
                    onClick={() => {
                      setValue(artist.name);
                      onSuggestionSelect?.(artist);
                      setHasFocus(false);
                      inputRef.current?.blur();
                    }}
                    role="option"
                    type="button"
                  >
                    <span className={styles.optionName}>{artist.name}</span>
                    <span className={styles.optionMeta}>
                      {artist.setCount} set{artist.setCount === 1 ? "" : "s"}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          ) : null}
          {helperText ? <div className={styles.helper}>{helperText}</div> : null}
        </div>
      ) : null}
    </div>
  );
}
