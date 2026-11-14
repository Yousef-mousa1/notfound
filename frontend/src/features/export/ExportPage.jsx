import { useState } from "react";
import { CheckCircle2, Download, FileDown, Loader2, XCircle } from "lucide-react";

import { createExport, downloadUrl, exportHistory } from "../../api/endpoints";
import Badge from "../../components/common/Badge";
import Panel from "../../components/common/Panel";
import { EmptyState, ErrorState, LoadingState } from "../../components/common/QueryState";
import { useApi } from "../../hooks/useApi";
import { dateTime, number } from "../../lib/format";

const EXPORT_ACTIONS = [
  {
    key: "observations-all",
    title: "All observations",
    description: "Every MODIS + VIIRS detection in the store, with a metadata sidecar.",
    request: () => createExport("observations", {}),
  },
  {
    key: "observations-modis",
    title: "MODIS observations",
    description: "Only MODIS detections (Terra + Aqua).",
    request: () => createExport("observations", { sensor: "modis" }),
  },
  {
    key: "observations-viirs",
    title: "VIIRS observations",
    description: "Only VIIRS detections (S-NPP).",
    request: () => createExport("observations", { sensor: "viirs" }),
  },
  {
    key: "harmonized",
    title: "Harmonized cell-days",
    description: "Latest harmonization run: one row per grid cell per day.",
    request: () => createExport("harmonized-data", {}),
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
  const history = useApi((options) => exportHistory({ ...options, limit: 25 }), []);
  const [running, setRunning] = useState(null);
  const [feedback, setFeedback] = useState({ key: null, type: null, message: "" });

  async function handleExport(action) {
    setRunning(action.key);
    setFeedback({ key: action.key, type: null, message: "" });

    try {
      const record = await action.request();
      setFeedback({
        key: action.key,
        type: "success",
        message: `Export ${record.export_id} created (${number(record.row_count)} rows).`,
      });
      history.reload();
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
          Every export writes new files and a metadata sidecar; stored data is never modified.
        </p>
      </div>

      <section className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
        {EXPORT_ACTIONS.map((action) => {
          const isRunning = running === action.key;
          const isSuccess = feedback.key === action.key && feedback.type === "success";
          const isError = feedback.key === action.key && feedback.type === "error";

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
                  disabled={isRunning}
                  onClick={() => handleExport(action)}
                  className="flex w-full items-center justify-center gap-2 rounded-lg bg-orange-500 px-3 py-2 text-xs font-semibold text-white transition hover:bg-orange-600 disabled:cursor-not-allowed disabled:opacity-60"
                >
                  {isRunning ? <Loader2 size={14} className="animate-spin" /> : <Download size={14} />}
                  {isRunning ? "Creating export…" : "Create export"}
                </button>

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

      <Panel
        title="Export history"
        description="Latest 25 exports with their files and download links."
        action={
          <button
            type="button"
            onClick={history.reload}
            className="text-xs font-medium text-orange-500 hover:text-orange-400"
          >
            Refresh
          </button>
        }
      >
        {history.loading && <LoadingState label="Loading export history…" />}
        {history.error && <ErrorState error={history.error} onRetry={history.reload} />}

        {!history.loading && !history.error && (history.data ?? []).length === 0 && (
          <EmptyState
            title="No exports yet"
            description="Create one of the exports above; it will appear here with a download link."
          />
        )}

        {(history.data ?? []).length > 0 && (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs leading-5 [&_td]:pr-4 [&_th]:pr-4 [&_td:last-child]:pr-0 [&_th:last-child]:pr-0">
              <thead className="text-(--text-secondary)">
                <tr className="border-b border-(--border-color)">
                  <th className="py-2 font-medium">Created</th>
                  <th className="py-2 font-medium">Kind</th>
                  <th className="py-2 font-medium">Status</th>
                  <th className="py-2 text-right font-medium">Rows</th>
                  <th className="py-2 font-medium">Files</th>
                </tr>
              </thead>
              <tbody>
                {(history.data ?? []).map((record) => (
                  <tr key={record.export_id} className="border-b border-(--border-color)/60 align-top last:border-0">
                    <td className="whitespace-nowrap py-2">{dateTime(record.created_at)}</td>
                    <td className="py-2">{record.kind}</td>
                    <td className="py-2">
                      <Badge variant={record.status === "succeeded" ? "neutral" : "extreme"}>
                        {record.status}
                      </Badge>
                    </td>
                    <td className="py-2 text-right">{number(record.row_count)}</td>
                    <td className="py-2">
                      <ul className="space-y-1">
                        {(record.files ?? []).map((file) => (
                          <li key={file.name}>
                            <a
                              href={downloadUrl(record, file.name)}
                              className="inline-flex items-center gap-1 whitespace-nowrap text-orange-500 hover:text-orange-400"
                              download
                            >
                              <Download size={12} />
                              {file.name}
                              <span className="text-(--text-secondary)">
                                ({(file.byte_size / 1024).toFixed(0)} KB)
                              </span>
                            </a>
                          </li>
                        ))}
                      </ul>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>
    </div>
  );
}
