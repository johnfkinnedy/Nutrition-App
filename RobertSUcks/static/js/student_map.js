let map, infoWindow, meMarker;

async function initMap() {
  const { Map } = await google.maps.importLibrary("maps");
  const { AdvancedMarkerElement, PinElement } = await google.maps.importLibrary("marker");

  map = new Map(document.getElementById("map"), {
    center: { lat: 36.3056589, lng: -82.3715495 }, // ETSU-ish fallback
    zoom: 12,
    mapId: "DEMO_MAP_ID"
  });

  infoWindow = new google.maps.InfoWindow();

  // ---- helper to save to Flask backend ----
  async function saveLocation(pos) {
    try {
      await fetch("/maps/update_location", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          latitude: pos.lat,
          longitude: pos.lng,
        })
      });
    } catch (e) {
      console.warn("Save failed:", e);
    }
  }

  // ---- place/update marker, center, and save ----
  function applyPosition(pos) {
    if (!meMarker) {
      const glyphText =
        typeof USER_INITIALS === "string" && USER_INITIALS.trim()
          ? USER_INITIALS.trim().toUpperCase()
          : "ST";

      const pin = new PinElement({
        glyph: glyphText,
        glyphColor: "white",
        background: "#00053E",
        borderColor: "#ffffff"
      });

      meMarker = new AdvancedMarkerElement({
        map,
        position: pos,
        content: pin.element
      });
    } else {
      meMarker.position = pos;
    }

    map.setCenter(pos);
    map.setZoom(15);
    saveLocation(pos); // store to DB on each update
  }

  const onSuccess = (position) =>
    applyPosition({
      lat: position.coords.latitude,
      lng: position.coords.longitude
    });

  const onError = (err) => {
    console.error("Geolocation error:", err);
  };

  // First fix:
  navigator.geolocation.getCurrentPosition(onSuccess, onError, {
    enableHighAccuracy: true
  });

  // Keep updating as they move:
  navigator.geolocation.watchPosition(onSuccess, onError, {
    enableHighAccuracy: true,
    maximumAge: 5000,
    timeout: 15000
  });
}

window.initMap = initMap;