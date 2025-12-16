// Ambil waktu sekarang dan tambahkan 1 tahun sebagai target
const now = new Date();
const targetDate = new Date(now);
targetDate.setFullYear(targetDate.getFullYear() + 1); // Tambah 1 tahun dari sekarang

// Fungsi untuk memperbarui countdown
function updateCountdown() {
    const now = new Date().getTime();
    const distance = targetDate.getTime() - now;

    if (distance < 0) {
        clearInterval(countdownInterval);
        document.getElementById("days").innerText = "00";
        document.getElementById("hours").innerText = "00";
        document.getElementById("minutes").innerText = "00";
        document.getElementById("seconds").innerText = "00";
        return;
    }

    const days = Math.floor(distance / (1000 * 60 * 60 * 24));
    const hours = Math.floor((distance % (1000 * 60 * 60 * 24)) / (1000 * 60 * 60));
    const minutes = Math.floor((distance % (1000 * 60 * 60)) / (1000 * 60));
    const seconds = Math.floor((distance % (1000 * 60)) / 1000);

    document.getElementById("days").innerText = String(days).padStart(2, '0');
    document.getElementById("hours").innerText = String(hours).padStart(2, '0');
    document.getElementById("minutes").innerText = String(minutes).padStart(2, '0');
    document.getElementById("seconds").innerText = String(seconds).padStart(2, '0');
}

// Jalankan countdown setiap detik
const countdownInterval = setInterval(updateCountdown, 1000);
updateCountdown(); // Panggil segera agar tidak delay

// Form submission
document.querySelector('.notify-form').addEventListener('submit', function(e) {
    e.preventDefault();
    alert("Email Anda telah terdaftar. Terima kasih!");
    this.reset();
});