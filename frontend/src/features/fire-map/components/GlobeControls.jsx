
import {
  Plus,
  Minus,
  RotateCcw,
  Pause,
  Play,
} from "lucide-react";

export default function GlobeControls({
  onZoomIn,
  onZoomOut,
  onReset,
  onToggleRotation,
  isAutoRotating,
}) {
  const buttonClass =
    "flex items-center justify-center p-3 text-slate-200 transition hover:bg-white/10 hover:text-orange-400";

  return (
    <div className="absolute right-5 top-5 z-10 flex flex-col overflow-hidden rounded-xl border border-white/10 bg-[#101827]/90 shadow-xl backdrop-blur-md">

      <button
        type="button"
        onClick={onZoomIn}
        className={buttonClass}
        aria-label="Zoom in"
        title="Zoom in"
      >
        <Plus size={18} />
      </button>

      <div className="h-px bg-white/10" />

      <button
        type="button"
        onClick={onZoomOut}
        className={buttonClass}
        aria-label="Zoom out"
        title="Zoom out"
      >
        <Minus size={18} />
      </button>

      <div className="h-px bg-white/10" />

      <button
        type="button"
        onClick={onReset}
        className={buttonClass}
        aria-label="Reset view"
        title="Reset view"
      >
        <RotateCcw size={17} />
      </button>

      <div className="h-px bg-white/10" />

      <button
        type="button"
        onClick={onToggleRotation}
        className={buttonClass}
        aria-label={
          isAutoRotating ? "Pause rotation" : "Start rotation"
        }
        title={
          isAutoRotating ? "Pause rotation" : "Start rotation"
        }
      >
        {isAutoRotating ? (
          <Pause size={17} />
        ) : (
          <Play size={17} />
        )}
      </button>
    </div>
  );
}
