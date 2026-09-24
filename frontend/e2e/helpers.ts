import type { APIRequestContext } from "@playwright/test";

export async function clearBrowserTestStudies(request: APIRequestContext): Promise<void> {
  const activeResponse = await request.get("/api/studies");
  if (!activeResponse.ok()) throw new Error("Could not read the isolated browser-test study store.");
  const active = (await activeResponse.json()).studies as Array<{ id: string; revision: number }>;
  for (const study of active) {
    const response = await request.delete(`/api/studies/${study.id}`, {
      headers: { "If-Match": `"${study.revision}"` },
    });
    if (!response.ok()) throw new Error("Could not clear an active browser-test study.");
  }

  const trashResponse = await request.get("/api/trash");
  if (!trashResponse.ok()) throw new Error("Could not read the isolated browser-test trash.");
  const trash = (await trashResponse.json()).studies as Array<{ id: string; revision: number }>;
  for (const study of trash) {
    const response = await request.delete(`/api/studies/${study.id}/permanent`, {
      headers: { "If-Match": `"${study.revision}"` },
    });
    if (!response.ok()) throw new Error("Could not clear a trashed browser-test study.");
  }
  const retentionResponse = await request.put("/api/retention", { data: { retention_days: 30 } });
  if (!retentionResponse.ok()) throw new Error("Could not reset the isolated browser-test retention policy.");
}
