// ── Map Setup ─────────────────────────────────────────────────────────────
// Initialise the map centred on the UK — will re-centre once we get location
const map = L.map("map").setView([52.5, -1.5], 6);

// Add OpenStreetMap tiles — this is the actual map imagery
L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    attribution: "© OpenStreetMap contributors",
}).addTo(map);

// ── Helper: Set Status Message ────────────────────────────────────────────
function setStatus(message) {
    document.getElementById("status").textContent = message;
}

// ── Helper: Get Sun Position via SunCalc ─────────────────────────────────
// SunCalc gives us altitude (height above horizon) and azimuth (compass direction)
// We convert azimuth from radians to degrees for the backend
function getSunPosition(lat, lng) {
    const now = new Date();
    const position = SunCalc.getPosition(now, lat, lng);
    return {
        altitude: ((position.altitude * 180) / Math.PI).toFixed(2),
        azimuth: ((position.azimuth * 180) / Math.PI + 180).toFixed(2),
    };
}

// ── Helper: Is It Sunny? ──────────────────────────────────────────────────
// Simple threshold check for marker colour — not the AI verdict, just the dot
function isSunny(cloudCover, sunAltitude) {
    return cloudCover < 60 && sunAltitude > 10;
}

// ── Helper: Create Coloured Marker ───────────────────────────────────────
function createMarker(sunny) {
    return L.divIcon({
        className: sunny ? "sunny-marker" : "cloudy-marker",
        iconSize: [24, 24],
        iconAnchor: [12, 12],
    });
}

// ── Close the Verdict Panel ───────────────────────────────────────────────
function closePanel() {
    document.getElementById("verdict-panel").classList.add("hidden");
}

// ── Render Forecast Blocks ────────────────────────────────────────────────
function renderForecast(forecastData, pubLat, pubLng) {
    const container = document.getElementById("forecast-bars");
    container.innerHTML = "";

    const now = new Date();

    forecastData.forEach((cloudCover, index) => {
        const futureTime = new Date(
            now.getTime() + (index + 1) * 60 * 60 * 1000,
        );
        const sunPos = SunCalc.getPosition(futureTime, pubLat, pubLng);
        const sunAltitude = (sunPos.altitude * 180) / Math.PI;
        const sunny = isSunny(cloudCover, sunAltitude);

        const hour = futureTime.getHours();
        const label = `${hour}:00`;

        const block = document.createElement("div");
        block.className = "forecast-block";
        block.style.background = sunny ? "var(--sunny)" : "var(--cloudy)";
        block.innerHTML = `
            <div>${sunny ? "☀️" : "☁️"}</div>
            <div>${label}</div>
            <div>${cloudCover}%</div>
        `;
        container.appendChild(block);
    });
}

// ── Fetch Verdict from Backend ────────────────────────────────────────────
async function fetchVerdict(
    pub,
    cloudCover,
    sunAltitude,
    sunAzimuth,
    forecast,
) {
    // Show the panel immediately with a loading message
    document.getElementById("pub-name").textContent = pub.title;
    document.getElementById("pub-address").textContent = pub.address;
    document.getElementById("verdict-text").textContent = "Getting verdict...";
    document.getElementById("verdict-panel").classList.remove("hidden");

    // Render forecast blocks immediately — no API call needed
    renderForecast(forecast, pub.latitude, pub.longitude);

    try {
        const response = await fetch("/verdict", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                pub_name: pub.title,
                address: pub.address,
                cloud_cover: cloudCover,
                sun_altitude: parseFloat(sunAltitude),
                sun_azimuth: parseFloat(sunAzimuth),
            }),
        });

        const verdict = await response.json();
        document.getElementById("verdict-text").textContent = verdict;
    } catch (error) {
        document.getElementById("verdict-text").textContent =
            "Sorry, couldn't get a verdict right now. Try again!";
    }
}

// ── Load Pubs onto the Map ────────────────────────────────────────────────
async function loadPubs(lat, lng) {
    setStatus("Finding nearby pubs...");

    try {
        // Fetch pubs from our FastAPI backend
        const response = await fetch(`/pubs?lat=${lat}&lng=${lng}`);
        const pubs = await response.json();

        if (pubs.length === 0) {
            setStatus("No pubs found nearby. Try a different location.");
            return;
        }

        setStatus(`Found ${pubs.length} pubs nearby — tap one for a verdict`);

        // For each pub, get weather and sun position, then add a marker
        for (const pub of pubs) {
            const pubLat = pub.latitude;
            const pubLng = pub.longitude;

            // Get cloud cover and forecast from our weather endpoint
            const weatherResponse = await fetch(
                `/weather?lat=${pubLat}&lng=${pubLng}`,
            );
            const weatherData = await weatherResponse.json();
            const cloudCover = weatherData.cloud_cover;
            const forecast = weatherData.forecast;

            // Get sun position from SunCalc (runs in browser, no API call needed)
            const sunPos = getSunPosition(pubLat, pubLng);
            const sunAltitude = sunPos.altitude;
            const sunAzimuth = sunPos.azimuth;

            // Decide marker colour
            const sunny = isSunny(cloudCover, parseFloat(sunAltitude));
            const marker = createMarker(sunny);

            // Add marker to map
            L.marker([pubLat, pubLng], { icon: marker })
                .addTo(map)
                .on("click", () => {
                    fetchVerdict(
                        pub,
                        cloudCover,
                        sunAltitude,
                        sunAzimuth,
                        forecast,
                    );
                });
        }
    } catch (error) {
        setStatus("Something went wrong loading pubs. Please refresh.");
        console.error(error);
    }
}

// ── Get User Location & Kick Everything Off ───────────────────────────────
if (navigator.geolocation) {
    navigator.geolocation.getCurrentPosition(
        (position) => {
            const lat = position.coords.latitude;
            const lng = position.coords.longitude;

            // Centre map on user
            map.setView([lat, lng], 15);

            // Add a marker for the user's position
            L.circleMarker([lat, lng], {
                radius: 8,
                fillColor: "#E8A020",
                color: "#1A1208",
                weight: 2,
                fillOpacity: 1,
            })
                .addTo(map)
                .bindPopup("You are here");

            // Load pubs around the user
            loadPubs(lat, lng);
        },
        (error) => {
            setStatus(
                "Location access denied — please enable location and refresh.",
            );
            console.error(error);
        },
    );
} else {
    setStatus("Geolocation is not supported by your browser.");
}
