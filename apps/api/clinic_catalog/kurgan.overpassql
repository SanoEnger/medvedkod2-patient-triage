[out:json][timeout:55];
rel(398427);
map_to_area->.city;
(
  node(area.city)["addr:housenumber"];
  way(area.city)["building"]["addr:housenumber"];
);
out body geom;
