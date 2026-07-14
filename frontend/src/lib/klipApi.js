import axios from "axios";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
export const API = `${BACKEND_URL}/api`;

const api = axios.create({ baseURL: API, timeout: 60000 });

export const listProjects = () => api.get("/projects").then((r) => r.data);
export const getProject = (id) => api.get(`/projects/${id}`).then((r) => r.data);
export const deleteProject = (id) => api.delete(`/projects/${id}`).then((r) => r.data);

export const uploadVideo = (file, onProgress) => {
    const fd = new FormData();
    fd.append("file", file);
    return api
        .post("/projects/upload", fd, {
            headers: { "Content-Type": "multipart/form-data" },
            timeout: 0,
            onUploadProgress: (evt) => {
                if (onProgress && evt.total)
                    onProgress(Math.round((evt.loaded * 100) / evt.total));
            },
        })
        .then((r) => r.data);
};

export const analyzeProject = (id) =>
    api.post(`/projects/${id}/analyze`).then((r) => r.data);
export const brollSearch = (pid, query) =>
    api.get(`/projects/${pid}/broll_search`, { params: { query } }).then((r) => r.data);
export const renderProject = (id, opts) =>
    api.post(`/projects/${id}/render`, opts).then((r) => r.data);

export const getKeysStatus = () => api.get("/keys/status").then((r) => r.data);
export const saveKeys = (keys) => api.post("/keys", keys).then((r) => r.data);
export const testKeys = () => api.post("/keys/test").then((r) => r.data);

export const mediaOriginal = (id) => `${API}/media/original/${id}`;
export const mediaOutput = (id) => `${API}/media/output/${id}`;
export const downloadUrl = (id) => `${API}/projects/${id}/download`;

export default api;
