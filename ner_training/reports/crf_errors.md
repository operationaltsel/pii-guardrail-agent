# Error analysis — `crf` on gold test set

Format: **gold** vs **pred** (tag inline). Hanya kalimat yang mengandung kesalahan.

Total kalimat dengan kesalahan: **22 / 135**

### [formal] #1
- gold: `Bapak <PERSON>Suryadi</PERSON> sudah membayar tagihan tetapi statusnya masih belum lunas.`
- pred: `Bapak Suryadi sudah membayar tagihan tetapi statusnya masih belum lunas.`
- missed (FN): `Suryadi` (PERSON)

### [formal] #2
- gold: `Terlampir bukti transfer atas nama <PERSON>Kurniawan Adi Saputra</PERSON> sebesar Rp250.000.`
- pred: `Terlampir bukti transfer atas nama <PERSON>Kurniawan Adi Saputra sebesar Rp250</PERSON>.000.`
- missed (FN): `Kurniawan Adi Saputra` (PERSON)
- spurious/boundary (FP): `Kurniawan Adi Saputra sebesar Rp250` (PERSON)

### [formal] #3
- gold: `Saya <PERSON>Christian Rumengan</PERSON> dari Manado ingin berhenti berlangganan.`
- pred: `Saya <PERSON>Christian Rumengan dari Manado</PERSON> ingin berhenti berlangganan.`
- missed (FN): `Christian Rumengan` (PERSON)
- spurious/boundary (FP): `Christian Rumengan dari Manado` (PERSON)

### [formal] #4
- gold: `Selamat sore. Saya <PERSON>Hendro Wibisono</PERSON>, pelanggan NusaTel sejak 2015. Sejak pindah ke <ADDRESS>Jl. Raya Darmo Indah Barat No. 7, Surabaya</ADDRESS>, koneksi sering putus terutama malam hari. Sudah tiga kali saya lapor lewat aplikasi tetapi belum ada teknisi yang datang. Mohon segera ditindaklanjuti. Terima kasih.`
- pred: `Selamat sore. Saya <PERSON>Hendro Wibisono</PERSON>, pelanggan NusaTel sejak 2015. Sejak pindah ke <ADDRESS>Jl. Raya Darmo Indah Barat No. 7, Surabaya, koneksi</ADDRESS> sering putus terutama malam hari. Sudah tiga kali saya lapor lewat aplikasi tetapi belum ada teknisi yang datang. Mohon segera ditindaklanjuti. Terima kasih.`
- missed (FN): `Jl. Raya Darmo Indah Barat No. 7, Surabaya` (ADDRESS)
- spurious/boundary (FP): `Jl. Raya Darmo Indah Barat No. 7, Surabaya, koneksi` (ADDRESS)

### [informal] #5
- gold: `sy tinggal di <ADDRESS>gg kenari 3 rt 5 rw 2 depok</ADDRESS>, sinyal jelek bgt dr kmrn`
- pred: `sy tinggal di <ADDRESS>gg kenari 3 rt 5 rw 2 depok, sinyal</ADDRESS> jelek bgt dr kmrn`
- missed (FN): `gg kenari 3 rt 5 rw 2 depok` (ADDRESS)
- spurious/boundary (FP): `gg kenari 3 rt 5 rw 2 depok, sinyal` (ADDRESS)

### [informal] #6
- gold: `bang teknisi namanya <PERSON>ujang</PERSON> blm dtg2 juga nih`
- pred: `bang teknisi namanya ujang blm dtg2 juga nih`
- missed (FN): `ujang` (PERSON)

### [informal] #7
- gold: `udh transfer tp blm masuk, nama rekening <PERSON>Wahyu Hidayat</PERSON>`
- pred: `udh transfer tp blm masuk, nama <PERSON>rekening Wahyu Hidayat</PERSON>`
- missed (FN): `Wahyu Hidayat` (PERSON)
- spurious/boundary (FP): `rekening Wahyu Hidayat` (PERSON)

### [informal] #8
- gold: `min <PERSON>tiara</PERSON> nih, kok sinyal 4g ilang ya`
- pred: `min tiara nih, kok sinyal 4g ilang ya`
- missed (FN): `tiara` (PERSON)

### [informal] #9
- gold: `td kurirnya pak <PERSON>slamet</PERSON> blg alamat ga ketemu`
- pred: `td kurirnya pak slamet blg alamat ga ketemu`
- missed (FN): `slamet` (PERSON)

### [informal] #10
- gold: `halo aku <PERSON>Gilang</PERSON> anaknya Bu <PERSON>Ratna</PERSON>, mau tanya tagihan`
- pred: `halo aku Gilang anaknya Bu <PERSON>Ratna</PERSON>, mau tanya tagihan`
- missed (FN): `Gilang` (PERSON)

### [multi_entity] #11
- gold: `Saya <PERSON>Agung Prasetyo</PERSON>, mau daftarkan istri saya <PERSON>Lina Marlina</PERSON> sebagai pengguna tambahan.`
- pred: `Saya <PERSON>Agung Prasetyo</PERSON>, mau daftarkan istri saya <PERSON>Lina Marlina sebagai pengguna tambahan</PERSON>.`
- missed (FN): `Lina Marlina` (PERSON)
- spurious/boundary (FP): `Lina Marlina sebagai pengguna tambahan` (PERSON)

### [multi_entity] #12
- gold: `Paket untuk <PERSON>Bambang</PERSON> dikirim ke <ADDRESS>Jl. Merdeka No. 1 Bogor</ADDRESS>, sedangkan paket untuk <PERSON>Yanti</PERSON> ke <ADDRESS>Jl. Pajajaran No. 20 Bogor</ADDRESS>.`
- pred: `Paket untuk Bambang dikirim ke <ADDRESS>Jl. Merdeka No. 1 Bogor</ADDRESS>, sedangkan paket untuk Yanti ke <ADDRESS>Jl. Pajajaran No. 20 Bogor</ADDRESS>.`
- missed (FN): `Bambang` (PERSON), `Yanti` (PERSON)

### [multi_entity] #13
- gold: `Anak saya <PERSON>Kevin</PERSON> dan <PERSON>Jessica</PERSON> sering pakai hotspot, apakah bisa tambah kuota keluarga?`
- pred: `Anak saya <PERSON>Kevin</PERSON> dan <PERSON>Jessica sering pakai hotspot</PERSON>, apakah bisa tambah kuota keluarga?`
- missed (FN): `Jessica` (PERSON)
- spurious/boundary (FP): `Jessica sering pakai hotspot` (PERSON)

### [multi_entity] #14
- gold: `Tolong sampaikan ke teknisi <PERSON>Hadi</PERSON> bahwa ibu saya <PERSON>Suminah</PERSON> ada di rumah setelah jam 3.`
- pred: `Tolong sampaikan ke teknisi Hadi bahwa ibu saya <PERSON>Suminah</PERSON> ada di rumah setelah jam 3.`
- missed (FN): `Hadi` (PERSON)

### [hard_names] #15
- gold: `Pagi min, <PERSON>Fajar</PERSON> di sini, sinyal hilang sejak fajar tadi.`
- pred: `Pagi min, Fajar di sini, sinyal hilang sejak fajar tadi.`
- missed (FN): `Fajar` (PERSON)

### [hard_names] #16
- gold: `Saya <PERSON>Wa Ode Nurhaya</PERSON> dari Baubau, jaringan di sini sering putus.`
- pred: `Saya <PERSON>Wa Ode Nurhaya dari Baubau</PERSON>, jaringan di sini sering putus.`
- missed (FN): `Wa Ode Nurhaya` (PERSON)
- spurious/boundary (FP): `Wa Ode Nurhaya dari Baubau` (PERSON)

### [hard_names] #17
- gold: `Anak saya namanya <PERSON>Rizki</PERSON>, semoga rezeki kita lancar ya min.`
- pred: `Anak saya <PERSON>namanya Rizki</PERSON>, semoga rezeki kita lancar ya min.`
- missed (FN): `Rizki` (PERSON)
- spurious/boundary (FP): `namanya Rizki` (PERSON)

### [hard_address] #18
- gold: `Saya di <ADDRESS>Apartemen Kalibata City Tower Flamboyan Lt. 11 No. 07</ADDRESS>, sinyal indoor lemah.`
- pred: `Saya di <ADDRESS>Apartemen Kalibata City Tower Flamboyan Lt. 11 No. 07, sinyal indoor lemah</ADDRESS>.`
- missed (FN): `Apartemen Kalibata City Tower Flamboyan Lt. 11 No. 07` (ADDRESS)
- spurious/boundary (FP): `Apartemen Kalibata City Tower Flamboyan Lt. 11 No. 07, sinyal indoor lemah` (ADDRESS)

### [hard_address] #19
- gold: `Kirim ke kantor desa, <ADDRESS>Desa Tanjung Sari RT 002 RW 001, Kab. Lampung Selatan</ADDRESS>.`
- pred: `Kirim ke kantor <ADDRESS>desa, Desa Tanjung Sari RT 002 RW 001, Kab. Lampung Selatan</ADDRESS>.`
- missed (FN): `Desa Tanjung Sari RT 002 RW 001, Kab. Lampung Selatan` (ADDRESS)
- spurious/boundary (FP): `desa, Desa Tanjung Sari RT 002 RW 001, Kab. Lampung Selatan` (ADDRESS)

### [negative] #20
- gold: `Semoga rezeki lancar dan jaya selalu untuk tim CS.`
- pred: `Semoga rezeki lancar dan <PERSON>jaya selalu</PERSON> untuk tim CS.`
- spurious/boundary (FP): `jaya selalu` (PERSON)

### [negative] #21
- gold: `Mau tanya, di Kota Malang sudah ada jaringan 5G?`
- pred: `Mau tanya, di <ADDRESS>Kota Malang</ADDRESS> sudah ada jaringan 5G?`
- spurious/boundary (FP): `Kota Malang` (ADDRESS)

### [mixed_pii] #22
- gold: `email saya andi.wijaya at gmail dot com ya kak`
- pred: `email saya <PERSON>andi</PERSON>.wijaya at gmail dot com ya kak`
- spurious/boundary (FP): `andi` (PERSON)
