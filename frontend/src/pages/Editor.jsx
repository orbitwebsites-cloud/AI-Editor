import { useEffect, useMemo, useRef, useState, useCallback } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { toast } from "sonner";
import {
    ArrowLeft,
    Download,
    Loader2,
    Scissors,
    Wand2,
    Volume2,
    Film,
    Zap,
    RefreshCw,
    Search,
    Check,
} from "lucide-react";
import {
    getProject,
    analyzeProject,
    brollSearch,
    renderProject,
    mediaOriginal,
    mediaOutput,
    downloadUrl,
} from "@/lib/klipApi";

const STATUS_LABELS = {
    uploaded: "UPLOADED",
    queued: "QUEUED",
    extracting_audio: "EXTRACTING AUDIO",
    transcribing: "TRANSCRIBING",
    analyzing: "AI ANALYZING",
    ready: "READY TO EDIT",
    queued_render: "QUEUED",
    rendering: "RENDERING",
    done: "DONE",
    error: "ERROR",
};

const IN_PROGRESS = new Set([
    "queued", "extracting_audio", "transcribing", "analyzing", "queued_render", "rendering",
]);

export default function Editor() {
    const { id } = useParams();
    const navigate = useNavigate();
    const [project, setProject] = useState(null);
    const [style, setStyle] = useState("tiktok");
    const [renderOpts, setRenderOpts] = useState({
        remove_fillers: true, captions: true, sfx: true, zoom_ins: true, broll: true,
    });
    const [excludedFillers, setExcludedFillers] = useState(new Set());
    const [addedFillers, setAddedFillers] = useState(new Set());
    const [brollByMoment, setBrollByMoment] = useState({});
    const [brollSelected, setBrollSelected] = useState({});
    const [searchingIdx, setSearchingIdx] = useState(null);
    const [renderStarting, setRenderStarting] = useState(false);
    const [currentTime, setCurrentTime] = useState(0);
    const videoRef = useRef();
    const transcriptRef = useRef();

    const refresh = useCallback(async () => {
        try { setProject(await getProject(id)); }
        catch { toast.error("Project not found"); navigate("/"); }
    }, [id, navigate]);

    useEffect(() => { refresh(); }, [refresh]);

    useEffect(() => {
        if (!project) return;
        if (!IN_PROGRESS.has(project.status)) return;
        const t = setInterval(refresh, 2500);
        return () => clearInterval(t);
    }, [project, refresh]);

    useEffect(() => {
        if (project && project.status === "uploaded") {
            analyzeProject(id).then(refresh).catch((e) =>
                toast.error(e?.response?.data?.detail || "Analysis failed to start"));
        }
    }, [project, id, refresh]);

    const words = project?.transcript?.words || [];
    const analysis = project?.analysis || {};
    const autoFillers = useMemo(() => new Set(analysis.filler_indices || []), [analysis.filler_indices]);
    const emphasisSet = useMemo(() => new Set(analysis.emphasis_indices || []), [analysis.emphasis_indices]);
    const brollMoments = analysis.broll_moments || [];

    const effectiveFillers = useMemo(() => {
        const s = new Set(autoFillers);
        excludedFillers.forEach((i) => s.delete(i));
        addedFillers.forEach((i) => s.add(i));
        return s;
    }, [autoFillers, excludedFillers, addedFillers]);

    const activeIdx = useMemo(() => {
        if (!words.length) return -1;
        for (let i = 0; i < words.length; i++) {
            const w = words[i];
            if (w.start <= currentTime && currentTime <= w.end + 0.05) return i;
        }
        return -1;
    }, [words, currentTime]);

    useEffect(() => {
        if (activeIdx < 0) return;
        const el = document.getElementById(`w-${activeIdx}`);
        if (el && transcriptRef.current) {
            const r = el.getBoundingClientRect();
            const cr = transcriptRef.current.getBoundingClientRect();
            if (r.top < cr.top + 40 || r.bottom > cr.bottom - 40) {
                el.scrollIntoView({ behavior: "smooth", block: "center" });
            }
        }
    }, [activeIdx]);

    const toggleFiller = (i) => {
        if (autoFillers.has(i)) {
            const s = new Set(excludedFillers);
            s.has(i) ? s.delete(i) : s.add(i);
            setExcludedFillers(s);
        } else {
            const s = new Set(addedFillers);
            s.has(i) ? s.delete(i) : s.add(i);
            setAddedFillers(s);
        }
    };

    const jumpTo = (i) => {
        const w = words[i];
        if (!w || !videoRef.current) return;
        videoRef.current.currentTime = w.start;
        videoRef.current.play();
    };

    const searchBrollForMoment = async (idx, query) => {
        setSearchingIdx(idx);
        try {
            const r = await brollSearch(id, query);
            setBrollByMoment((prev) => ({ ...prev, [idx]: r.results || [] }));
        } catch (e) { toast.error("B-roll search failed"); }
        finally { setSearchingIdx(null); }
    };

    const startRender = async () => {
        setRenderStarting(true);
        const selected_broll = Object.entries(brollSelected)
            .filter(([, v]) => v)
            .map(([idx, v]) => ({
                word_index: brollMoments[idx]?.word_index || 0,
                video_url: v.video_url,
            }));
        const opts = {
            style,
            ...renderOpts,
            excluded_filler_indices: [...excludedFillers],
            added_filler_indices: [...addedFillers],
            selected_broll,
        };
        try {
            await renderProject(id, opts);
            toast.success("Render started");
            refresh();
        } catch (e) {
            toast.error(e?.response?.data?.detail || "Render failed");
        } finally { setRenderStarting(false); }
    };

    if (!project) {
        return (
            <div className="min-h-[70vh] flex items-center justify-center text-white/40" data-testid="editor-loading">
                <Loader2 className="w-6 h-6 animate-spin" />
            </div>
        );
    }

    const inProgress = IN_PROGRESS.has(project.status);
    const isReady = project.status === "ready" || project.status === "done";
    const isDone = project.status === "done";

    return (
        <div className="min-h-[calc(100vh-72px)] px-4 md:px-8 py-8" data-testid="editor-page">
            <div className="flex items-center justify-between mb-6">
                <button onClick={() => navigate("/")} className="btn-ghost" data-testid="back-btn">
                    <ArrowLeft className="w-4 h-4" /> Back
                </button>
                <div className="text-right">
                    <div className="font-display text-2xl md:text-3xl tracking-wider truncate max-w-md">
                        {analysis.title || project.name}
                    </div>
                    <div className="font-mono text-xs text-white/40 mt-1">
                        {Math.round(project.duration)}s · {project.width}x{project.height} ·
                        <span className={`ml-2 ${project.status === "error" ? "text-[#ff3333]" : "text-[#ccff00]"}`}>
                            {STATUS_LABELS[project.status] || project.status?.toUpperCase()}
                        </span>
                    </div>
                </div>
            </div>

            {inProgress && (
                <div className="panel p-12 mb-6 trace-border" data-testid="processing-panel">
                    <div className="flex items-center gap-6">
                        <Loader2 className="w-10 h-10 text-[#ccff00] animate-spin flex-shrink-0" />
                        <div className="flex-1">
                            <div className="font-display text-4xl md:text-5xl tracking-wider text-[#ccff00]">
                                {STATUS_LABELS[project.status]}
                            </div>
                            <div className="text-white/60 text-sm mt-2">{project.status_message}</div>
                            <div className="h-1 bg-white/10 mt-4">
                                <div
                                    className="h-1 bg-[#ccff00] transition-all"
                                    style={{ width: `${project.progress || 0}%` }}
                                />
                            </div>
                        </div>
                    </div>
                </div>
            )}

            {project.status === "error" && (
                <div className="panel p-6 mb-6" style={{ borderColor: "rgba(255,51,51,0.4)" }} data-testid="error-panel">
                    <div className="font-display text-2xl text-[#ff3333]">ERROR</div>
                    <div className="text-white/70 text-sm mt-2">{project.status_message}</div>
                    <button className="btn-ghost mt-4" onClick={() =>
                        analyzeProject(id).then(refresh)} data-testid="retry-btn">
                        <RefreshCw className="w-4 h-4" /> Retry Analysis
                    </button>
                </div>
            )}

            <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
                <div className="lg:col-span-2 space-y-6">
                    <div className="panel">
                        <video
                            ref={videoRef}
                            src={isDone ? mediaOutput(project.id) : mediaOriginal(project.id)}
                            controls
                            className="w-full aspect-video bg-black"
                            onTimeUpdate={(e) => setCurrentTime(e.target.currentTime)}
                            data-testid="video-player"
                        />
                        {isDone && (
                            <div className="p-4 flex items-center justify-between border-t border-white/10">
                                <div className="font-mono text-xs text-[#ccff00] tracking-widest">
                                    ✓ EDITED VERSION LOADED
                                </div>
                                <a
                                    href={downloadUrl(project.id)}
                                    className="btn-brand"
                                    data-testid="download-btn"
                                    download
                                >
                                    <Download className="w-4 h-4" /> Download MP4
                                </a>
                            </div>
                        )}
                    </div>

                    {isReady && words.length > 0 && (
                        <div className="panel">
                            <div className="px-6 py-4 border-b border-white/10 flex items-center justify-between">
                                <div>
                                    <div className="font-display text-xl tracking-wider">TRANSCRIPT</div>
                                    <div className="font-mono text-[10px] text-white/40 tracking-widest">
                                        {words.length} WORDS · {effectiveFillers.size} FLAGGED FOR CUT · CLICK WORDS TO TOGGLE
                                    </div>
                                </div>
                                <div className="font-mono text-xs text-white/50">
                                    {Math.round(currentTime)}s
                                </div>
                            </div>
                            <div
                                ref={transcriptRef}
                                className="p-6 max-h-[420px] overflow-y-auto text-lg md:text-xl leading-relaxed"
                                data-testid="transcript-area"
                            >
                                {words.map((w, i) => {
                                    const isFiller = effectiveFillers.has(i);
                                    const isEmph = emphasisSet.has(i);
                                    const isActive = i === activeIdx;
                                    let cls = "word-clickable ";
                                    if (isFiller) cls += "word-filler ";
                                    if (isEmph && !isFiller) cls += "word-emphasis ";
                                    if (isActive) cls += "word-active ";
                                    return (
                                        <span
                                            key={i}
                                            id={`w-${i}`}
                                            className={cls}
                                            onClick={() => toggleFiller(i)}
                                            onDoubleClick={() => jumpTo(i)}
                                            title={`${w.start?.toFixed(2)}s · click to toggle cut · dbl-click to jump`}
                                        >
                                            {w.word}{" "}
                                        </span>
                                    );
                                })}
                            </div>
                        </div>
                    )}
                </div>

                {isReady && (
                <aside className="space-y-6" data-testid="editor-sidebar">
                    <div className="panel p-6">
                        <div className="font-mono text-xs text-white/40 tracking-widest mb-3">// STYLE</div>
                        <div className="grid grid-cols-2 gap-2">
                            <button
                                className={`style-pill ${style === "tiktok" ? "active-tiktok" : ""}`}
                                onClick={() => setStyle("tiktok")}
                                data-testid="style-tiktok"
                            >
                                TIKTOK
                            </button>
                            <button
                                className={`style-pill ${style === "youtube" ? "active-youtube" : ""}`}
                                onClick={() => setStyle("youtube")}
                                data-testid="style-youtube"
                            >
                                YOUTUBE
                            </button>
                        </div>
                        <div className="text-xs text-white/50 mt-3">
                            {style === "tiktok"
                                ? "Bold Impact font. Pink emphasis. Bounce animations. Aggressive."
                                : "Clean Arial. Yellow emphasis. Subtle. Studio-look."}
                        </div>
                    </div>

                    <div className="panel p-6 space-y-4">
                        <div className="font-mono text-xs text-white/40 tracking-widest">// FEATURES</div>
                        <Toggle
                            icon={Scissors}
                            label="Cut fillers"
                            sub={`${effectiveFillers.size} words flagged`}
                            checked={renderOpts.remove_fillers}
                            onChange={(v) => setRenderOpts((o) => ({ ...o, remove_fillers: v }))}
                            testid="toggle-fillers"
                        />
                        <Toggle
                            icon={Wand2}
                            label="Animated captions"
                            sub="Word-by-word pop"
                            checked={renderOpts.captions}
                            onChange={(v) => setRenderOpts((o) => ({ ...o, captions: v }))}
                            testid="toggle-captions"
                        />
                        <Toggle
                            icon={Zap}
                            label="Emphasis zoom"
                            sub={`${emphasisSet.size} moments`}
                            checked={renderOpts.zoom_ins}
                            onChange={(v) => setRenderOpts((o) => ({ ...o, zoom_ins: v }))}
                            testid="toggle-zoom"
                        />
                        <Toggle
                            icon={Volume2}
                            label="SFX (whoosh on cuts)"
                            sub="Auto-mixed"
                            checked={renderOpts.sfx}
                            onChange={(v) => setRenderOpts((o) => ({ ...o, sfx: v }))}
                            testid="toggle-sfx"
                        />
                        <Toggle
                            icon={Film}
                            label="B-roll overlays"
                            sub={`${Object.values(brollSelected).filter(Boolean).length} selected`}
                            checked={renderOpts.broll}
                            onChange={(v) => setRenderOpts((o) => ({ ...o, broll: v }))}
                            testid="toggle-broll"
                        />
                    </div>

                    <button
                        onClick={startRender}
                        disabled={renderStarting || project.status === "rendering"}
                        className="btn-brand w-full !justify-center text-lg"
                        data-testid="render-btn"
                    >
                        {renderStarting ? <Loader2 className="w-4 h-4 animate-spin" /> : <Zap className="w-5 h-5" />}
                        {isDone ? "Re-Render" : "Render Final"}
                    </button>

                    <div className="text-center font-mono text-[10px] text-white/30 tracking-widest">
                        POWERED BY GROQ · CEREBRAS · PEXELS
                    </div>
                </aside>
                )}
            </div>

            {isReady && brollMoments.length > 0 && renderOpts.broll && (
                <section className="mt-8" data-testid="broll-section">
                    <div className="font-mono text-xs text-white/40 tracking-widest mb-2">// B-ROLL SUGGESTIONS</div>
                    <div className="font-display text-3xl tracking-wider mb-6">DROP-INS</div>
                    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                        {brollMoments.map((m, idx) => {
                            const results = brollByMoment[idx] || [];
                            const selected = brollSelected[idx];
                            return (
                                <div key={idx} className="panel p-5" data-testid={`broll-moment-${idx}`}>
                                    <div className="font-mono text-[10px] text-white/40 tracking-widest">
                                        @ WORD #{m.word_index}
                                    </div>
                                    <div className="font-display text-xl tracking-wider mt-1">
                                        &quot;{(m.query || "").toUpperCase()}&quot;
                                    </div>
                                    <div className="text-white/50 text-xs mt-1">{m.reason}</div>
                                    <button
                                        onClick={() => searchBrollForMoment(idx, m.query)}
                                        disabled={searchingIdx === idx}
                                        className="btn-ghost mt-3 !text-xs !py-1.5"
                                        data-testid={`broll-search-${idx}`}
                                    >
                                        {searchingIdx === idx ? (
                                            <Loader2 className="w-3 h-3 animate-spin" />
                                        ) : (
                                            <Search className="w-3 h-3" />
                                        )}
                                        {results.length ? "Refresh" : "Search Pexels"}
                                    </button>
                                    {results.length > 0 && (
                                        <div className="grid grid-cols-2 gap-2 mt-3">
                                            {results.slice(0, 4).map((r) => {
                                                const active = selected?.id === r.id;
                                                return (
                                                    <div
                                                        key={r.id}
                                                        className="relative cursor-pointer border"
                                                        style={{
                                                            borderColor: active ? "#CCFF00" : "rgba(255,255,255,0.1)",
                                                        }}
                                                        onClick={() =>
                                                            setBrollSelected((s) => ({
                                                                ...s,
                                                                [idx]: active ? undefined : r,
                                                            }))
                                                        }
                                                        data-testid={`broll-clip-${idx}-${r.id}`}
                                                    >
                                                        <img
                                                            src={r.thumbnail}
                                                            alt=""
                                                            className="w-full h-20 object-cover"
                                                        />
                                                        {active && (
                                                            <div className="absolute inset-0 bg-[#ccff00]/20 flex items-center justify-center">
                                                                <Check className="w-6 h-6 text-[#ccff00]" strokeWidth={3} />
                                                            </div>
                                                        )}
                                                    </div>
                                                );
                                            })}
                                        </div>
                                    )}
                                </div>
                            );
                        })}
                    </div>
                </section>
            )}
        </div>
    );
}

function Toggle({ icon: Icon, label, sub, checked, onChange, testid }) {
    return (
        <label
            className="flex items-center gap-3 cursor-pointer group"
            data-testid={testid}
        >
            <div
                className="w-10 h-5 relative flex-shrink-0 border"
                style={{
                    background: checked ? "#CCFF00" : "transparent",
                    borderColor: checked ? "#CCFF00" : "rgba(255,255,255,0.25)",
                }}
            >
                <div
                    className="absolute top-0.5 w-4 h-4 transition-all"
                    style={{
                        left: checked ? "calc(100% - 1.125rem)" : "0.125rem",
                        background: checked ? "#000" : "rgba(255,255,255,0.5)",
                    }}
                />
                <input type="checkbox" className="opacity-0 absolute inset-0"
                    checked={checked} onChange={(e) => onChange(e.target.checked)} />
            </div>
            <Icon className={`w-4 h-4 ${checked ? "text-[#ccff00]" : "text-white/40"} flex-shrink-0`} />
            <div className="flex-1 min-w-0">
                <div className={`text-sm font-semibold ${checked ? "text-white" : "text-white/60"}`}>
                    {label}
                </div>
                <div className="text-[10px] font-mono text-white/40 tracking-wider truncate">{sub}</div>
            </div>
        </label>
    );
}
