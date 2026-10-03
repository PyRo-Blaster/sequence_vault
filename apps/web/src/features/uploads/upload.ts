import { api, rawFetch, unwrap } from "../../lib/api";
import { sha256Hex } from "../../lib/sha256";

export interface UploadOutcome {
  name: string;
  taskId?: string;
  error?: unknown;
}

/** Declare, upload and complete one file. The server verifies size and SHA-256. */
export async function uploadFile(file: File, projectId: string): Promise<UploadOutcome> {
  try {
    const bytes = await file.arrayBuffer();
    const declared = await unwrap(
      api.POST("/v1/uploads", {
        body: {
          project_id: projectId,
          file_name: file.name,
          byte_count: bytes.byteLength,
          sha256: await sha256Hex(bytes),
        },
      }),
    );
    await rawFetch(declared.upload_url, {
      method: "PUT",
      body: bytes,
      headers: { "Content-Type": "application/octet-stream" },
    });
    const completed = await unwrap(
      api.POST("/v1/uploads/{file_id}/complete", {
        params: { path: { file_id: declared.file_id } },
      }),
    );
    return { name: file.name, taskId: completed.task_id };
  } catch (error) {
    return { name: file.name, error };
  }
}
