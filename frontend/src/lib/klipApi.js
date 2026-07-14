import axios from "axios";

const BACKEND_URL = (process.env.REACT_APP_BACKEND_URL || window.location.origin).replace(/\/$/, "");
export const API = `${BACKEND_URL}/api`;

const api = axios.create({ baseURL: API, timeout: 60000 });

export const listProjects = () => api.get("/projects").then((r) => r.data);
export const getProject = (id) => api.get(`/projects/${id}`).then((r) => r.data);
export const deleteProject = (id) => api.delete(`/projects/${id}`).then((r) => r.data);

// Chunked upload with per-chunk retries + resume support.
// - Chunk size: 4MB (safely under any ingress limit).
// - Retries: each chunk up to 4 times with exponential backoff.
// - Resume: previously-uploaded upload_id (from localStorage keyed by file identity)
//   is checked via /uploads/status to skip already-received chunks.
const CHUNK_SIZE = 4 * 1024 * 1024;
const MAX_CHUNK_RETRIES = 4;

// Storage key so a page reload lets user retry same file without re-uploading chunks
const RESUME_KEY = (file) => `klippd_resume_${file.name}_${file.size}_${file.lastModified}`;

const readResumeId = (key) => {
    try { return window.localStorage.getItem(key); }
    catch { return null; }
};

const writeResumeId = (key, value) => {
    try { window.localStorage.setItem(key, value); }
    catch { /* Upload still works when storage is blocked. */ }
};

const clearResumeId = (key) => {
    try { window.localStorage.removeItem(key); }
    catch { /* Nothing else to clean up. */ }
};

export const apiErrorMessage = (error, fallback = "Something went wrong") => {
    const detail = error?.response?.data?.detail;
    if (typeof detail === "string" && detail.trim()) return detail;
    if (error?.code === "ECONNABORTED") return "The server took too long to respond. Try again.";
    if (!error?.response && error?.message === "Network Error") {
        return "Cannot reach the Klipped Studio server. Check the backend URL and try again.";
    }
    return error?.message || fallback;
};

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function uploadChunkWithRetry(uploadId, index, blob, onChunkProgress) {
    let lastErr = null;
    for (let attempt = 0; attempt < MAX_CHUNK_RETRIES; attempt++) {
        try {
            const fd = new FormData();
            fd.append("file", blob, `chunk_${index}`);
            await api.post(`/uploads/chunk/${uploadId}?index=${index}`, fd, {
                timeout: 0,
                onUploadProgress: onChunkProgress,
            });
            return;
        } catch (e) {
            lastErr = e;
            const status = e?.response?.status;
            // 404 (session gone) or 4xx client errors → do not retry
            if (status === 404 || (status >= 400 && status < 500 && status !== 408 && status !== 429)) {
                throw e;
            }
            const backoff = Math.min(8000, 500 * 2 ** attempt) + Math.random() * 400;
            await sleep(backoff);
        }
    }
    throw lastErr;
}

export const uploadVideo = async (file, onProgress) => {
    const total_chunks = Math.max(1, Math.ceil(file.size / CHUNK_SIZE));

    // Try to resume an existing session for this exact file
    const resumeKey = RESUME_KEY(file);
    let upload_id = null;
    let received = new Set();
    const cached = readResumeId(resumeKey);
    if (cached) {
        try {
            const { data: st } = await api.get(`/uploads/status/${cached}`);
            if (st?.total_chunks === total_chunks && st?.size === file.size) {
                upload_id = cached;
                received = new Set(st.received_chunks || []);
            }
        } catch {
            // Session expired/gone — fall through to fresh init
            clearResumeId(resumeKey);
        }
    }

    // Fresh init if no resumable session
    if (!upload_id) {
        const { data: init } = await api.post("/uploads/init", {
            filename: file.name,
            size: file.size,
            total_chunks,
        });
        upload_id = init.upload_id;
        writeResumeId(resumeKey, upload_id);
    }

    // Upload each chunk not yet received
    let uploadedBytes = [...received].reduce((total, index) => {
        if (!Number.isInteger(index) || index < 0 || index >= total_chunks) return total;
        const start = index * CHUNK_SIZE;
        return total + Math.max(0, Math.min(CHUNK_SIZE, file.size - start));
    }, 0);
    if (onProgress) onProgress(Math.min(99, Math.round((uploadedBytes / file.size) * 100)));

    for (let i = 0; i < total_chunks; i++) {
        if (received.has(i)) continue;
        const start = i * CHUNK_SIZE;
        const end = Math.min(file.size, start + CHUNK_SIZE);
        const chunkSize = end - start;
        const chunk = file.slice(start, end);

        await uploadChunkWithRetry(upload_id, i, chunk, (evt) => {
            if (onProgress && file.size) {
                const currentChunkLoaded = evt.loaded || 0;
                const pct = Math.round(((uploadedBytes + currentChunkLoaded) / file.size) * 100);
                onProgress(Math.min(99, pct));
            }
        });

        uploadedBytes += chunkSize;
        received.add(i);
        if (onProgress) onProgress(Math.min(99, Math.round((uploadedBytes / file.size) * 100)));
    }

    // Finalize
    const { data: project } = await api.post(`/uploads/finalize/${upload_id}`);
    clearResumeId(resumeKey);
    if (onProgress) onProgress(100);
    return project;
};

export const analyzeProject = (id) =>
    api.post(`/projects/${id}/analyze`).then((r) => r.data);
export const brollSearch = (pid, query) =>
    api.get(`/projects/${pid}/broll_search`, { params: { query } }).then((r) => r.data);
export const uploadCustomBroll = (pid, file, onProgress) => {
    const fd = new FormData();
    fd.append("file", file);
    return api
        .post(`/projects/${pid}/broll_upload`, fd, {
            timeout: 0,
            onUploadProgress: (evt) => {
                if (onProgress && evt.total)
                    onProgress(Math.round((evt.loaded * 100) / evt.total));
            },
        })
        .then((r) => r.data);
};
export const extractViralClips = (pid) =>
    api.post(`/projects/${pid}/viral_clips`).then((r) => r.data);
export const renderProject = (id, opts) =>
    api.post(`/projects/${id}/render`, opts).then((r) => r.data);

export const getKeysStatus = () => api.get("/keys/status").then((r) => r.data);
export const saveKeys = (keys) => api.post("/keys", keys).then((r) => r.data);
export const testKeys = () => api.post("/keys/test").then((r) => r.data);

export const mediaOriginal = (id) => `${API}/media/original/${id}`;
export const mediaOutput = (id) => `${API}/media/output/${id}`;
export const mediaClip = (id, label) => `${API}/media/clip/${id}/${encodeURIComponent(label)}`;
export const mediaThumbnail = () => null;
export const downloadUrl = (id, clipLabel) =>
    clipLabel
        ? `${API}/projects/${id}/download?clip=${encodeURIComponent(clipLabel)}`
        : `${API}/projects/${id}/download`;

export default api;
