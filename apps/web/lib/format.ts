export const formatTimestamp = (value: Date | string | null | undefined) => {
  if (!value) {
    return "n/a";
  }

  const date = value instanceof Date ? value : new Date(value);
  return Number.isNaN(date.getTime()) ? "n/a" : date.toISOString();
};
