import { NavLink } from "react-router-dom";
import {
  LayoutDashboard,
  Map,
  CalendarDays,
  CalendarRange,
  ChartNoAxesCombined,
  Download,
  Flame,
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

export default function Sidebar() {
  return (
    <aside className="w-64 shrink-0 border-r border-(--border-color) bg-(--surface) p-5">
      <div className="mb-10 flex items-center gap-3">
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
              className={({ isActive }) =>
                `flex items-center gap-3 rounded-lg px-3 py-3 text-sm font-medium transition-colors ${
                  isActive
                    ? "bg-orange-500/10 text-orange-500"
                    : "text-(--text-secondary) hover:bg-(--surface-secondary) hover:text-(--text-primary)"
                }`
              }
            >
              <Icon size={19} />
              {item.label}
            </NavLink>
          );
        })}
      </nav>
    </aside>
  );
}