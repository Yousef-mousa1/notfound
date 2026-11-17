import { Link } from "react-router-dom";
import { Flame, House, Map } from "lucide-react";

export default function NotFoundPage() {
  return (
    <div className="flex min-h-[70vh] items-center justify-center px-4">
      <div className="w-full max-w-lg text-center">
        <div className="mx-auto mb-6 flex h-20 w-20 items-center justify-center rounded-2xl bg-orange-500/10">
          <Flame className="text-orange-500" size={40} />
        </div>

        <p className="mb-2 text-7xl font-black tracking-tighter text-orange-500 sm:text-8xl">
          404
        </p>

        <h1 className="mb-3 text-2xl font-bold text-(--text-primary) sm:text-3xl">
          Page not found
        </h1>

        <p className="mx-auto mb-8 max-w-md text-sm leading-relaxed text-(--text-secondary)">
          This route doesn&apos;t exist. The link may be outdated, or the page
          may have moved. Nothing here changes the data or the model.
        </p>

        <div className="flex flex-wrap items-center justify-center gap-3">
          <Link
            to="/"
            className="inline-flex items-center gap-2 rounded-lg bg-orange-500 px-5 py-3 text-sm font-semibold text-white transition-colors hover:bg-orange-600"
          >
            <House size={18} />
            Back to Overview
          </Link>

          <Link
            to="/map"
            className="inline-flex items-center gap-2 rounded-lg border border-(--border-color) bg-(--surface) px-5 py-3 text-sm font-semibold text-(--text-primary) transition-colors hover:bg-(--surface-secondary)"
          >
            <Map size={18} />
            Open Fire Map
          </Link>
        </div>
      </div>
    </div>
  );
}
