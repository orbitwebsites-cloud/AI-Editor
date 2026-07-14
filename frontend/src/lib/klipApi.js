import axios from "axios";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
export const API = `${BACKEND_URL}/api`;

const api = axios.create({ baseURL: API, timeout: 60000 });

export const listProjects = () => api.get("/projects").then((r) => r.data);
export const getProject = (id) => api.get(`/projects/${id}`).then((r) => r.data);
export const deleteProject = (id) => api.delete(`/projects/${id}`).then((r) => r.data);

// Chunked upload: bypass ingress 413 by splitting file into small chunks.
// Chunk size = 4MB (safely under any ingress limit).
const CHUNK_SIZE = 4 * 1024 * 1024;

export const uploadVideo = async (file, onProgress) => {
    const total_chunks = Math.max(1, Math.ceil(file.size / CHUNK_SIZE));
    // 1. init
    const { data: init } = await api.post("/uploads/init", {
        filename: file.name,
        size: file.size,
        total_chunks,
    });
    const upload_id = init.upload_id;

    // 2. upload chunks sequentially
    let uploaded = 0;
    for (let i = 0; i < total_chunks; i++) {
        const start = i * CHUNK_SIZE;
        const end = Math.min(file.size, start + CHUNK_SIZE);
        const chunk = file.slice(start, end);
        const fd = new FormData();
        fd.append("file", chunk, `chunk_${i}`);
        await api.post(`/uploads/chunk/${upload_id}?index=${i}`, fd, {
            headers: { "Content-Type": "multipart/form-data" },
            timeout: 0,
            onUploadProgress: (evt) => {
                if (onProgress && file.size) {
                    const currentChunkLoaded = evt.loaded || 0;
                    const pct = Math.round(((uploaded + currentChunkLoaded) / file.size) * 100);
                    onProgress(Math.min(99, pct));
                }
            },
        });
        uploaded += (end - start);
        if (onProgress) onProgress(Math.min(99, Math.round((uploaded / file.size) * 100)));
    }

    // 3. finalize
    const { data: project } = await api.post(`/uploads/finalize/${upload_id}`);
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
            headers: { "Content-Type": "multipart/form-data" },
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
