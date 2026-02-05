let map;

async function initMap() {
  const { Map } = await google.maps.importLibrary("maps");
  const { AdvancedMarkerElement, PinElement } = await google.maps.importLibrary("marker");

  const etsuCenter = { lat: 36.3056589, lng: -82.3715495 };

  map = new Map(document.getElementById("map"), {
    center: etsuCenter,
    zoom: 12,
    mapId: "DEMO_MAP_ID"
  });

  const statusEl = document.getElementById("status");

  try {
    const resp = await fetch("/maps/active_students");
    const data = await resp.json();

    if (data.status !== "ok") {
      statusEl.textContent = "Error loading student locations.";
      console.error(data);
      return;
    }

    const students = data.students || [];

    if (!students.length) {
      statusEl.textContent = "No student locations available.";
      return;
    }

    statusEl.textContent = `Showing ${students.length} student(s).`;

    const bounds = new google.maps.LatLngBounds();

    for (const s of students) {
      const pos = { lat: s.lat, lng: s.lng };
      bounds.extend(pos);

      const pin = new PinElement({
        glyph: s.initials,
        glyphColor: "white",
        background: "#00053E",
        borderColor: "#ffffff"
      });

      new AdvancedMarkerElement({
        map,
        position: pos,
        content: pin.element,
        title: `Student ID: ${s.student_id}`
      });
    }

    map.fitBounds(bounds);
  } catch (err) {
    statusEl.textContent = "Error retrieving student data.";
    console.error(err);
  }
}

window.initMap = initMap;