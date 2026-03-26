type RequestPayload = Record<string, FormDataEntryValue | FormDataEntryValue[]>;

const toRecord = (formData: FormData): RequestPayload => {
  const entries: RequestPayload = {};

  for (const [key, value] of formData.entries()) {
    if (key in entries) {
      const current = entries[key];
      entries[key] = Array.isArray(current) ? [...current, value] : [current, value];
      continue;
    }

    entries[key] = value;
  }

  return entries;
};

export const readRequestBody = async (request: Request) => {
  const contentType = request.headers.get("content-type") ?? "";

  if (contentType.includes("application/json")) {
    return (await request.json()) as RequestPayload;
  }

  const formData = await request.formData();
  return toRecord(formData);
};

export const isJsonRequest = (request: Request) =>
  (request.headers.get("content-type") ?? "").includes("application/json");
