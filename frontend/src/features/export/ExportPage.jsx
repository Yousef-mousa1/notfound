import { useState } from "react";
import { CheckCircle2, Download, FileDown, Info, Loader2, XCircle } from "lucide-react";

import { createExport } from "../../api/endpoints";

// Vercel Functions cap a response at 4.5 MB. Exports beyond that cannot be
// downloaded in one stateless request, so they are disabled in this demo
// rather than failing with a 413 after the user clicks. Row counts come from
// the shipped read-only snapshot (verified 2026-11-17).
const DEMO_LIMIT_NOTE =
  "Not available in the demo: this export exceeds the 4.5 MB download limit of the free host.";

const EXPORT_ACTIONS = [
  {
    key: "observations-all",
    title: "All observations",
    description: "Every MODIS + VIIRS detection in the store, with a metadata sidecar.",
    demoLimit: "261,415 rows (~37 MB)",
    request: () => createExport("observations", {}),
  },
  {
    key: "observations-modis",
    title: "MODIS observations",
    description: "Only MODIS detections (Terra + Aqua).",
    demoLimit: "131,653 rows (~18 MB)",
    request: () => createExport("observations", { sensor: "modis" }),
  },
  {
    key: "observations-viirs",
    title: "VIIRS observations",
    description: "Only VIIRS detections (S-NPP).",
    demoLimit: "129,762 rows (~18 MB)",
    request: () => createExport("observations", { sensor: "viirs" }),
  },
  {
    key: "harmonized",
    title: "Harmonized cell-days",
    description: "Latest harmonization run: one row per grid cell per day.",
    demoLimit: "219,986 rows (~30 MB)",
    request: () => createExport("harmonized-data", {}),
  },
  {
    key: "estimates",
    title: "Harmonized estimates (model)",
    description:
      "Full model series: 2013/2024/2025 observed + backcasts, both scales separate. Model-produced, not FIRMS detections.",
    demoLimit: "813,254 rows (~80 MB)",
    request: () => createExport("estimate-series", {}),
  },
  {
    key: "estimates-viirs",
    title: "VIIRS-harmonized estimates",
    description:
      "Only the coverage-corrected VIIRS scale of the model series.",
    demoLimit: "406,627 rows (~40 MB)",
    request: () => createExport("estimate-series", { scale: "viirs_harmonized" }),
  },
  {
    key: "validation",
    title: "Validation report",
    description: "JSON report of the latest validation run, including matched pairs.",
    request: () => createExport("validation-report", { include_pairs: true }),
  },
  {
    key: "anomalies",
    title: "Anomalies CSV",
    description: "All flagged anomalies from the latest anomaly run.",
    request: () => createExport("csv", { source: "anomalies" }),
  },
];

export default function ExportPage() {
  const [running, setRunning] = useState(null);
  const [feedback, setFeedback] = useState({ key: null, type: null, message: "" });

  async function handleExport(action) {
    setRunning(action.key);
    setFeedback({ key: action.key, type: null, message: "Preparing your file…" });

    try {
      const result = await action.request();
      setFeedback({
        key: action.key,
        type: "success",
        message: `Downloaded ${result.fileName}. The ZIP also contains the metadata and limitations.`,
      });
    } catch (error) {
      setFeedback({ key: action.key, type: "error", message: error.message });
    } finally {
      setRunning(null);
    }
  }

  return (
    <div className="space-y-7">
      <div>
        <h2 className="text-2xl font-bold">Export center</h2>
        <p className="mt-1 text-sm text-(--text-secondary)">
          Press Export and your file downloads immediately. Each ZIP contains the
          data plus a metadata file with the inputs, steps and known limitations.
          Nothing is saved to an export history.
        </p>
      </div>

      <section className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
        {EXPORT_ACTIONS.map((action) => {
          const isRunning = running === action.key;
          const isSuccess = feedback.key === action.key && feedback.type === "success";
          const isError = feedback.key === action.key && feedback.type === "error";
          const unavailable = Boolean(action.demoLimit);

          return (
            <div
              key={action.key}
              className="flex flex-col justify-between rounded-xl border border-(--border-color) bg-(--surface) p-5"
            >
              <div>
                <div className="flex items-center gap-2">
                  <FileDown size={17} className="text-orange-500" />
                  <h3 className="text-sm font-semibold">{action.title}</h3>
                </div>
                <p className="mt-2 text-xs leading-5 text-(--text-secondary)">
                  {action.description}
                </p>
              </div>

              <div className="mt-4">
                <button
                  type="button"
                  disabled={unavailable || isRunning}
                  onClick={() => handleExport(action)}
                  className="flex w-full items-center justify-center gap-2 rounded-lg bg-orange-500 px-3 py-2 text-xs font-semibold text-white transition hover:bg-orange-600 disabled:cursor-not-allowed disabled:opacity-60"
                >
                  {unavailable ? <Info size={14} /> : isRunning ? <Loader2 size={14} className="animate-spin" /> : <Download size={14} />}
                  {unavailable ? "Unavailable in demo" : isRunning ? "Preparing file…" : "Export"}
                </button>

                {unavailable ? (
                  <p className="mt-2 flex items-start gap-1.5 text-[11px] leading-4 text-(--text-secondary)">
                    <Info size={13} className="mt-0.5 shrink-0" />
                    <span>
                      {DEMO_LIMIT_NOTE} <strong>{action.demoLimit}</strong>
                    </span>
                  </p>
                ) : null}

                {feedback.key === action.key && feedback.message && (
                  <p
                    className={`mt-2 flex items-start gap-1.5 text-[11px] leading-4 ${isSuccess ? "text-emerald-600 dark:text-emerald-400" : isError ? "text-red-500" : "text-(--text-secondary)"}`}
                  >
                    {isSuccess ? <CheckCircle2 size={13} className="mt-0.5 shrink-0" /> : null}
                    {isError ? <XCircle size={13} className="mt-0.5 shrink-0" /> : null}
                    {feedback.message}
                  </p>
                )}
              </div>
            </div>
          );
        })}
      </section>
    </div>
  );
}
