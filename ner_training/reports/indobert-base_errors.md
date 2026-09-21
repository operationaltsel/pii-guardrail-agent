# Error analysis — `indobert-base` on gold test set

Format: **gold** vs **pred** (tag inline). Hanya kalimat yang mengandung kesalahan.

Total kalimat dengan kesalahan: **4 / 135**

### [informal] #1
- gold: `halo aku <PERSON>Gilang</PERSON> anaknya Bu <PERSON>Ratna</PERSON>, mau tanya tagihan`
- pred: `halo aku <PERSON>Gilang anaknya</PERSON> Bu <PERSON>Ratna</PERSON>, mau tanya tagihan`
- missed (FN): `Gilang` (PERSON)
- spurious/boundary (FP): `Gilang anaknya` (PERSON)

### [hard_names] #2
- gold: `Pagi min, <PERSON>Fajar</PERSON> di sini, sinyal hilang sejak fajar tadi.`
- pred: `Pagi min, Fajar di sini, sinyal hilang sejak fajar tadi.`
- missed (FN): `Fajar` (PERSON)

### [hard_address] #3
- gold: `Kirim ke kantor desa, <ADDRESS>Desa Tanjung Sari RT 002 RW 001, Kab. Lampung Selatan</ADDRESS>.`
- pred: `Kirim ke <ADDRESS>kantor desa, Desa Tanjung Sari RT 002 RW 001, Kab. Lampung Selatan</ADDRESS>.`
- missed (FN): `Desa Tanjung Sari RT 002 RW 001, Kab. Lampung Selatan` (ADDRESS)
- spurious/boundary (FP): `kantor desa, Desa Tanjung Sari RT 002 RW 001, Kab. Lampung Selatan` (ADDRESS)

### [mixed_pii] #4
- gold: `email saya andi.wijaya at gmail dot com ya kak`
- pred: `email saya <PERSON>andi.wijaya</PERSON> at gmail dot com ya kak`
- spurious/boundary (FP): `andi.wijaya` (PERSON)
