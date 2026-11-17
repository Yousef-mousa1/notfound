import { NavLink } from "react-router-dom";
import {
  LayoutDashboard,
  Map,
  CalendarDays,
  CalendarRange,
  ChartNoAxesCombined,
  Download,
  Flame,
  X,
} from "lucide-react";

const navigation = [
  {
    label: "Overview",
    path: "/",
    icon: LayoutDashboard,
  },
  {
    label: "Fire Map",
    path: "/map",
    icon: Map,
  },
  {
    label: "Activity Calendar",
    path: "/calendar",
    icon: CalendarDays,
  },
  {
    label: "Harmonized Calendar",
    path: "/harmonized",
    icon: CalendarRange,
  },
  {
    label: "Analytics",
    path: "/analytics",
    icon: ChartNoAxesCombined,
  },
  {
    label: "Export Center",
    path: "/export",
    icon: Download,
  },
];

export default function Sidebar({ open, onClose }) {
  return (
    <aside
      className={`fixed inset-y-0 left-0 z-40 w-64 shrink-0 transform border-r border-(--border-color) bg-(--surface) p-5 transition-transform duration-200 lg:sticky lg:top-0 lg:h-screen lg:translate-x-0 ${
        open ? "translate-x-0" : "-translate-x-full"
      }`}
    >
      <div className="mb-10 flex items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <div className="rounded-xl bg-orange-500/10 p-2.5">
            <Flame className="text-orange-500" size={25} />
          </div>

          <div>
            <h1 className="text-lg font-bold tracking-tight">
              PyroScope
            </h1>

            <p className="text-xs text-(--text-secondary)">
              Satellite Intelligence
            </p>
          </div>
        </div>

        {/* زرار الإغلاق — موبايل بس */}
        <button
          type="button"
          aria-label="Close navigation"
          onClick={onClose}
          className="rounded-lg p-2 text-(--text-secondary) hover:bg-(--surface-secondary) lg:hidden"
        >
          <X size={20} />
        </button>
      </div>

      <p className="mb-3 px-3 text-xs font-semibold uppercase tracking-wider text-(--text-secondary)">
        Workspace
      </p>

      <nav className="space-y-1">
        {navigation.map((item) => {
          const Icon = item.icon;

          return (
            <NavLink
              key={item.path}
              to={item.path}
              end={item.path === "/"}
              onClick={onClose}
              className={({ isActive }) =>
                `flex items-center gap-3 rounded-lg px-3 py-3 text-sm font-medium transition-colors ${
                  isActive
                    ? "bg-orange-500/10 text-orange-500"
                    : "text-(--text-secondary) hover:bg-(--surface-secondary) hover:text-(--text-primary)"
                }`
              }
            >
              <Icon size={19} className="shrink-0" />
              <span className="truncate">{item.label}</span>
            </NavLink>
          );
        })}
      </nav>
    </aside>
  );
}
