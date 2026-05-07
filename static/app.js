// ── Map Setup ─────────────────────────────────────────────────────────────
const map = L.map("map").setView([52.5, -1.5], 6);

L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    attribution: "© OpenStreetMap contributors",
}).addTo(map);

// Track which pubs have already been added to avoid duplicates on pan
const addedPubs = new Set();
let isLoading = false;

// ── Helper: Set Status Message ────────────────────────────────────────────
function setStatus(message) {
    document.getElementById("status").textContent = message;
}

// ── Helper: Get Sun Position via SunCalc ─────────────────────────────────
function getSunPosition(lat, lng) {
    const now = new Date();
    const position = SunCalc.getPosition(now, lat, lng);
    return {
        altitude: ((position.altitude * 180) / Math.PI).toFixed(2),
        azimuth: ((position.azimuth * 180) / Math.PI + 180).toFixed(2),
    };
}

// ── Helper: Is It Sunny? ──────────────────────────────────────────────────
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

// ── User Report ───────────────────────────────────────────────────────────
let currentReport = {};

function resetReport() {
    document.getElementById("question-1").classList.remove("hidden");
    document.getElementById("question-2").classList.add("hidden");
    document.getElementById("question-3").classList.add("hidden");
    document.getElementById("report-thanks").classList.add("hidden");
}

function hideReport() {
    document.getElementById("report-section").classList.add("hidden");
}

function showQuestion2() {
    document.getElementById("question-1").classList.add("hidden");
    document.getElementById("question-2").classList.remove("hidden");
}

function setSunny(value) {
    currentReport.sunny = value;
    document.getElementById("question-2").classList.add("hidden");
    document.getElementById("question-3").classList.remove("hidden");
}

function setGarden(value) {
    currentReport.garden = value;
    document.getElementById("question-3").classList.add("hidden");
    document.getElementById("report-thanks").classList.remove("hidden");
    submitReport();
}

async function submitReport() {
    console.log("Submitting report:", currentReport);
    try {
        await fetch("/report", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                pub_id: currentReport.pub_id,
                pub_name: currentReport.pub_name,
                sunny: currentReport.sunny,
                garden: currentReport.garden,
                cloud_cover: currentReport.cloud_cover,
                sun_altitude: currentReport.sun_altitude,
            }),
        });
    } catch (error) {
        console.error("Error submitting report:", error);
    }
}

// ── Search This Area Button ───────────────────────────────────────────────
function searchArea() {
    const centre = map.getCenter();
    loadPubs(centre.lat, centre.lng);
}

// ── Render Forecast Blocks ────────────────────────────────────────────────
function renderForecast(forecastData, pubLat, pubLng) {
    if (!forecastData) return;
    const container = document.getElementById("forecast-bars");
    container.innerHTML = "";
    const now = new Date();
    const sunset = SunCalc.getTimes(now, pubLat, pubLng).sunset; // calculate the sunset hour

    forecastData.forEach((cloudCover, index) => {
        const futureTime = new Date(now.getTime() + index * 60 * 60 * 1000);
        const sunPos = SunCalc.getPosition(futureTime, pubLat, pubLng);
        const sunAltitude = (sunPos.altitude * 180) / Math.PI;
        const sunny = isSunny(cloudCover, sunAltitude);
        const hour = futureTime.getHours();

        if (futureTime > sunset) return; // stop rendering blocks after sunset

        const block = document.createElement("div");
        block.className = "forecast-block";
        block.style.background = sunny ? "var(--sunny)" : "var(--cloudy)";
        const label = index === 0 ? "Now" : `${hour}:00`;
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
    document.getElementById("pub-name").textContent = pub.title;
    document.getElementById("pub-address").textContent = pub.address;
    document.getElementById("verdict-text").textContent = "Getting verdict...";
    document.getElementById("verdict-panel").classList.remove("hidden");

    renderForecast(forecast, pub.latitude, pub.longitude);
    currentReport = {
        pub_id: pub.id,
        pub_name: pub.title,
        cloud_cover: cloudCover,
        sun_altitude: parseFloat(sunAltitude),
    };
    document.getElementById("report-section").classList.remove("hidden");
    resetReport();
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
    if (isLoading) return;
    isLoading = true;
    setStatus("Finding nearby pubs...");

    try {
        const response = await fetch(`/pubs?lat=${lat}&lng=${lng}`);
        const pubs = await response.json();

        if (pubs.length === 0) {
            setStatus("No pubs found nearby. Try a different location.");
            return;
        }

        setStatus(`Found ${pubs.length} pubs nearby — tap one for a verdict`);

        for (const pub of pubs) {
            if (addedPubs.has(pub.id)) continue;
            addedPubs.add(pub.id);

            const pubLat = pub.latitude;
            const pubLng = pub.longitude;

            const weatherResponse = await fetch(
                `/weather?lat=${pubLat}&lng=${pubLng}`,
            );
            const weatherData = await weatherResponse.json();
            const cloudCover = weatherData.cloud_cover;
            const forecast = weatherData.forecast;

            const sunPos = getSunPosition(pubLat, pubLng);
            const sunAltitude = sunPos.altitude;
            const sunAzimuth = sunPos.azimuth;

            const sunny = isSunny(cloudCover, parseFloat(sunAltitude));
            const marker = createMarker(sunny);

            L.marker([pubLat, pubLng], { icon: marker, interactive: true })
                .addTo(map)
                .bindTooltip(pub.title, {
                    permanent: false,
                    direction: "top",
                    offset: [0, -12],
                })
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
    } finally {
        isLoading = false;
    }
}

// ── Get User Location & Kick Everything Off ───────────────────────────────
if (navigator.geolocation) {
    navigator.geolocation.getCurrentPosition(
        (position) => {
            const lat = position.coords.latitude;
            const lng = position.coords.longitude;

            map.setView([lat, lng], 15);

            L.circleMarker([lat, lng], {
                radius: 8,
                fillColor: "#E8A020",
                color: "#1A1208",
                weight: 2,
                fillOpacity: 1,
            })
                .addTo(map)
                .bindPopup("You are here");

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

// ── Close Panel on Pan ────────────────────────────────────────────────────
map.on("movestart", () => {
    closePanel();
});
