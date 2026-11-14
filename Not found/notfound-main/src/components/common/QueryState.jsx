import { AlertTriangle, Inbox, Loader2 } from "lucide-react";

export function LoadingState({ label = "Loading data from the API…" }) {
  return (
    <div className="flex min-h-40 flex-col items-center justify-center gap-3 text-center">
      <Loader2 className="animate-spin text-orange-500" size={26} />
      <p className="text-xs text-(--text-secondary)">{label}</p>
    </div>
  );
}

export function ErrorState({ error, onRetry }) {
  const isNetwork = error?.isNetworkError;

  return (
    <div className="flex min-h-40 flex-col items-center justify-center gap-3 px-4 text-center">
      <div className="rounded-2xl bg-red-500/10 p-3">
        <AlertTriangle className="text-red-500" size={24} />
      </div>
      <div>
        <p className="text-sm font-semibold">
          {isNetwork ? "Backend not reachable" : "The API returned an error"}
        </p>
        <p className="mx-auto mt-1 max-w-md text-xs leading-5 text-(--text-secondary)">
          {error?.message ?? "Unknown error."}
        </p>
        {error?.status ? (
          <p className="mt-1 text-[11px] text-(--text-secondary)">
            HTTP {error.status}
            {error?.code ? ` · ${error.code}` : ""}
          </p>
        ) : null}
      </div>
      {onRetry && (
        <button
          type="button"
          onClick={onRetry}
          className="rounded-lg bg-orange-500 px-3 py-1.5 text-xs font-semibold text-white hover:bg-orange-600"
        >
          Retry
        </button>
      )}
    </div>
  );
}

export function EmptyState({ title = "Nothing to show", description, icon: Icon = Inbox }) {
  return (
    <div className="flex min-h-40 flex-col items-center justify-center gap-3 px-4 text-center">
      <div className="rounded-2xl bg-(--surface-secondary) p-3">
        <Icon className="text-(--text-secondary)" size={24} />
      </div>
      <div>
        <p className="text-sm font-semibold">{title}</p>
        {description && (
          <p className="mx-auto mt-1 max-w-sm text-xs leading-5 text-(--text-secondary)">
            {description}
          </p>
        )}
      </div>
    </div>
  );
}
