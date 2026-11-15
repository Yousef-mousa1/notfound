// مربعات تقريبية (bounding boxes) لاختيار منطقة في الـ calendar.
// دي مش حدود دول: بتتداخل مع بعض شوية وبتشمل بحر ودول مجاورة.
export const REGION_PRESETS = [
  { region: "africa", label: "Africa", bbox: { min_lon: -18, min_lat: -35, max_lon: 52, max_lat: 37 } },
  { region: "europe", label: "Europe", bbox: { min_lon: -25, min_lat: 35, max_lon: 45, max_lat: 72 } },
  { region: "middle_east", label: "Middle East", bbox: { min_lon: 34, min_lat: 12, max_lon: 63, max_lat: 42 } },
  { region: "asia", label: "Asia", bbox: { min_lon: 60, min_lat: -11, max_lon: 180, max_lat: 78 } },
  { region: "north_america", label: "North America", bbox: { min_lon: -170, min_lat: 7, max_lon: -50, max_lat: 84 } },
  { region: "south_america", label: "South America", bbox: { min_lon: -82, min_lat: -56, max_lon: -34, max_lat: 13 } },
  { region: "oceania", label: "Oceania", bbox: { min_lon: 110, min_lat: -48, max_lon: 180, max_lat: -1 } },
];