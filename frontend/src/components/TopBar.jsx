import { Link, useLocation } from "react-router-dom";
import { Settings, Sparkles, CheckCircle2, XCircle } from "lucide-react";

export default function TopBar({ keysStatus, onOpenSettings }) {
    const loc = useLocation();
    const configured =
        keysStatus.groq && (keysStatus.cerebras || true) && keysStatus.pexels;
    const groqOk = keysStatus.groq;
    return (
        <header
            className="w-full border-b border-white/10 bg-[#050505] sticky top-0 z-40"
            data-testid="top-bar"
        >
            <div className="flex items-center justify-between px-6 py-4">
                <Link
                    to="/"
                    className="flex items-center gap-3 group"
                    data-testid="brand-link"
                >
                    <div className="w-9 h-9 bg-[#ccff00] flex items-center justify-center">
                        <Sparkles className="w-5 h-5 text-black" strokeWidth={3} />
                    </div>
                    <div>
                        <div className="font-heading text-2xl leading-none tracking-wider">
                            KLIPPD
                        </div>
                        <div className="font-mono text-[10px] text-white/50 tracking-widest">
                            AI EDITOR / v0.1
                        </div>
                    </div>
                </Link>
                <div className="flex items-center gap-4">
                    <div className="hidden md:flex items-center gap-3 text-xs font-mono">
                        <StatusPill label="GROQ" ok={groqOk} />
                        <StatusPill label="CEREBRAS" ok={keysStatus.cerebras} />
                        <StatusPill label="PEXELS" ok={keysStatus.pexels} />
                    </div>
                    <button
                        onClick={onOpenSettings}
                        className="btn-ghost !py-2 !px-3"
                        data-testid="open-settings-btn"
                    >
                        <Settings className="w-4 h-4" />
                        <span className="hidden md:inline">Keys</span>
                    </button>
                </div>
            </div>
        </header>
    );
}

function StatusPill({ label, ok }) {
    return (
        <div
            className="flex items-center gap-1.5 px-2 py-1 border border-white/10"
            data-testid={`status-${label.toLowerCase()}`}
        >
            {ok ? (
                <CheckCircle2 className="w-3 h-3 text-[#ccff00]" />
            ) : (
                <XCircle className="w-3 h-3 text-white/30" />
            )}
            <span className={ok ? "text-white/90" : "text-white/40"}>
                {label}
            </span>
        </div>
    );
}
