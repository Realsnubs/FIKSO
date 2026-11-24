// DEMO LAYER — not real published services. Loaded only with VITE_CATALOGUE_DEMO=true (catalogue/publicCatalogue.ts).
//
// Catalogue structure, names, descriptions and W-IDs: docs/CATALOGUE_SEED.md (where every service is still a draft).
// `orderable` here is a demo flag to show the order flow; real orderability comes from the backend
// (catalogue.availability). Services that need a qualification stay not orderable, as no qualification is configured.
// Page texts and photos of three specialisations: fiksoapp.eu (lampu-un-gaismeklu-uzstadisana, santehnikas-sikdarbi
// and the home page work gallery), Latvian only — no translation is approved yet.
import type { PublicCatalogue, SpecialisationContent } from '../types/publicCatalogue'
import griestu1 from './images/griestu-1.jpg'
import griestu2 from './images/griestu-2.jpg'
import jaucejkrans from './images/jaucejkrans-pec.webp'
import lampa from './images/lampa-pec.webp'
import sifons from './images/sifons-pec.webp'
import spogulisPec from './images/spogulis-pec.jpg'
import spogulisPirms from './images/spogulis-pirms.jpg'

const CONTENT: Record<string, SpecialisationContent> = {
  "Gaismekļu meistars": {
    title: { lv: 'Lampu un gaismekļu uzstādīšana Rīgā un Pierīgā' },
    lead: { lv: 'Uzstādām lampas un gaismekļus uz jau sagatavotiem elektrības pieslēgumiem Rīgā un Pierīgā.' },
    canDo: [
      { lv: 'Griestu lampu un plafonu uzstādīšana' },
      { lv: 'Sienas gaismekļu montāža' },
      { lv: 'Esoša gaismekļa nomaiņa' },
      { lv: 'Gaismekļa stiprinājuma pielāgošana' },
      { lv: 'Vairāku gaismekļu uzstādīšana vienā vizītē' },
    ],
    prepare: [
      {
        lv: 'Atsūti esošā pieslēguma, griestu vai sienas un jaunā gaismekļa foto. Ja nepieciešama jauna elektroinstalācija vai bojājumu novēršana, pirms vizītes pateiksim, vai vajadzīgs cits speciālists.',
      },
    ],
    photos: [
      {
        src: spogulisPirms,
        kind: 'before',
        alt: { lv: 'Vannasistabas siena un pagaidu spuldze pirms spoguļa un sienas gaismekļa uzstādīšanas' },
        caption: { lv: 'Spogulis un sienas gaismeklis — pirms darba' },
      },
      {
        src: spogulisPec,
        kind: 'after',
        alt: { lv: 'Vannasistabā uzstādīts spogulis un sienas gaismeklis pie esoša pieslēguma' },
        caption: { lv: 'Spogulis un sienas gaismeklis — paveiktais darbs' },
      },
      {
        src: griestu1,
        kind: 'after',
        alt: { lv: 'Uzstādīti griestu gaismekļi — reāls FIKSO paveiktais darbs' },
        caption: { lv: 'Griestu gaismekļi — paveiktais darbs' },
      },
      {
        src: griestu2,
        kind: 'after',
        alt: { lv: 'Uzstādīts griestu gaismeklis — reāla darba rezultāts' },
        caption: { lv: 'Griestu gaismeklis — paveiktais darbs' },
      },
    ],
    cardImage: { src: lampa, alt: { lv: 'Jauns dekoratīvs griestu gaismeklis pēc uzstādīšanas dzīvoklī Rīgā' } },
  },
  "Izlietņu meistars": {
    faq: [
      {
        question: { lv: 'Kādus nelielus santehnikas darbus var pieteikt?' },
        answer: {
          lv: 'Var pieteikt jaucējkrāna, sifona un WC mehānisma remontu vai nomaiņu, sadzīves tehnikas pieslēgšanu un nelielu noplūžu vai savienojumu pārbaudi. Konkrēto situāciju precizējam pēc apraksta un foto.',
        },
      },
      {
        question: { lv: 'Ko atsūtīt pirms meistara izsaukuma?' },
        answer: {
          lv: 'Atsūti kopskata foto, bojātās vietas tuvplānu un īsu aprakstu par to, kas notiek. Ja zināms detaļas ražotājs vai modelis, pievieno arī šo informāciju.',
        },
      },
      {
        question: { lv: 'Kur FIKSO veic santehnikas sīkdarbus?' },
        answer: {
          lv: 'FIKSO strādā Rīga un Pierīga. Ja neesi pārliecināts par konkrēto adresi, sazinies ar mums pirms pieteikuma.',
        },
      },
    ],
    cardImage: { src: sifons, alt: { lv: 'Jauns izlietnes sifons pēc nomaiņas dzīvoklī Rīgā' } },
  },
  "Krānu meistars": {
    cardImage: { src: jaucejkrans, alt: { lv: 'Jauns vannas istabas izlietnes jaucējkrāns pēc uzstādīšanas Rīgā' } },
  },
}

export const demoCatalogue: PublicCatalogue = {
  demo: true,
  categories: [
    {
      id: "cm-c1",
      name: { lv: "Mazā santehnika un mājas meistaru darbi" },
      specialisations: [
      {
        id: "cm-s01",
        categoryId: "cm-c1",
        name: { lv: "Poda meistars" },
        description: { lv: "podu uzstādīšana, nomaiņa, skalojamo kastu un mehānismu remonts." },
        status: "active",
        content: CONTENT["Poda meistars"] ?? null,
        services: [
        { id: "cm-s01-1", wId: "W071", name: { lv: "Tualetes poda uzstādīšana" }, orderable: true },
        { id: "cm-s01-2", wId: "W072", name: { lv: "Tualetes poda nomaiņa" }, orderable: true },
        { id: "cm-s01-3", wId: "W073", name: { lv: "Skalošanas kastes remonts" }, orderable: true },
        { id: "cm-s01-4", wId: "W074", name: { lv: "Skalošanas mehānisma remonts" }, orderable: true },
        ],
      },
      {
        id: "cm-s02",
        categoryId: "cm-c1",
        name: { lv: "Krānu meistars" },
        description: { lv: "virtuves un vannasistabas jaucējkrānu, maisītāju uzstādīšana un nomaiņa." },
        status: "active",
        content: CONTENT["Krānu meistars"] ?? null,
        services: [
        { id: "cm-s02-1", wId: "W075", name: { lv: "Jaucējkrāna uzstādīšana" }, orderable: true },
        { id: "cm-s02-2", wId: "W076", name: { lv: "Jaucējkrāna nomaiņa" }, orderable: true },
        ],
      },
      {
        id: "cm-s03",
        categoryId: "cm-c1",
        name: { lv: "Izlietņu meistars" },
        description: { lv: "izlietņu uzstādīšana, sifonu nomaiņa, remonts un pieslēgšana." },
        status: "active",
        content: CONTENT["Izlietņu meistars"] ?? null,
        services: [
        { id: "cm-s03-1", wId: "W077", name: { lv: "Izlietnes uzstādīšana" }, orderable: true },
        { id: "cm-s03-2", wId: "W078", name: { lv: "Sifona nomaiņa" }, orderable: true },
        { id: "cm-s03-3", wId: "W079", name: { lv: "Izlietnes vai sifona remonts" }, orderable: true },
        { id: "cm-s03-4", wId: "W080", name: { lv: "Izlietnes pieslēgšana" }, orderable: true },
        ],
      },
      {
        id: "cm-s04",
        categoryId: "cm-c1",
        name: { lv: "Tehnikas meistars" },
        description: { lv: "veļas un trauku mazgājamo mašīnu pieslēgšana, uzstādīšana." },
        status: "active",
        content: CONTENT["Tehnikas meistars"] ?? null,
        services: [
        { id: "cm-s04-1", wId: "W081", name: { lv: "Veļas mazgājamās mašīnas uzstādīšana un pieslēgšana" }, orderable: true },
        { id: "cm-s04-2", wId: "W082", name: { lv: "Trauku mazgājamās mašīnas uzstādīšana un pieslēgšana" }, orderable: true },
        ],
      },
      {
        id: "cm-s05",
        categoryId: "cm-c1",
        name: { lv: "Silikona meistars" },
        description: { lv: "vecā silikona noņemšana, jaunu silikona šuvju ieklāšana vannasistabās, dušās un virtuvēs." },
        status: "active",
        content: CONTENT["Silikona meistars"] ?? null,
        services: [
        { id: "cm-s05-1", wId: "W083", name: { lv: "Vecā silikona noņemšana" }, orderable: true },
        { id: "cm-s05-2", wId: "W084", name: { lv: "Jaunu silikona šuvju ieklāšana" }, orderable: true },
        ],
      },
      {
        id: "cm-s06",
        categoryId: "cm-c1",
        name: { lv: "Stiprinājumu meistars" },
        description: { lv: "televizoru, plauktu, spoguļu, karnīžu, žalūziju, turētāju un citu priekšmetu stiprināšana." },
        status: "active",
        content: CONTENT["Stiprinājumu meistars"] ?? null,
        services: [
        { id: "cm-s06-1", wId: "W085", name: { lv: "Televizora stiprināšana" }, orderable: true },
        { id: "cm-s06-2", wId: "W086", name: { lv: "Plauktu stiprināšana" }, orderable: true },
        { id: "cm-s06-3", wId: "W087", name: { lv: "Spoguļa uzstādīšana un stiprināšana" }, orderable: true },
        { id: "cm-s06-4", wId: "W088", name: { lv: "Karnīzes uzstādīšana" }, orderable: true },
        { id: "cm-s06-5", wId: "W089", name: { lv: "Žalūziju stiprināšana" }, orderable: true },
        { id: "cm-s06-6", wId: "W090", name: { lv: "Turētāju stiprināšana" }, orderable: true },
        { id: "cm-s06-7", wId: "W091", name: { lv: "Citu priekšmetu stiprināšana" }, orderable: true },
        ],
      },
      {
        id: "cm-s07",
        categoryId: "cm-c1",
        name: { lv: "Gaismekļu meistars" },
        description: { lv: "lampu, lustru un gaismekļu uzstādīšana un nomaiņa pie esošiem pieslēgumiem." },
        status: "active",
        content: CONTENT["Gaismekļu meistars"] ?? null,
        services: [
        { id: "cm-s07-1", wId: "W092", name: { lv: "Gaismekļa uzstādīšana pie esoša pieslēguma" }, orderable: true },
        { id: "cm-s07-2", wId: "W093", name: { lv: "Gaismekļa nomaiņa pie esoša pieslēguma" }, orderable: true },
        ],
      },
      {
        id: "cm-s08",
        categoryId: "cm-c1",
        name: { lv: "Mēbeļu meistars" },
        description: { lv: "skapju, gultu, galdu un citu mēbeļu montāža, nelieli mēbeļu remonti." },
        status: "active",
        content: CONTENT["Mēbeļu meistars"] ?? null,
        services: [
        { id: "cm-s08-1", wId: "W094", name: { lv: "Skapja montāža" }, orderable: true },
        { id: "cm-s08-2", wId: "W095", name: { lv: "Gultas montāža" }, orderable: true },
        { id: "cm-s08-3", wId: "W096", name: { lv: "Galda montāža" }, orderable: true },
        { id: "cm-s08-4", wId: "W097", name: { lv: "Citu mēbeļu montāža" }, orderable: true },
        { id: "cm-s08-5", wId: "W098", name: { lv: "Neliels mēbeļu remonts" }, orderable: true },
        ],
      },
      {
        id: "cm-s09",
        categoryId: "cm-c1",
        name: { lv: "Vannasistabas meistars" },
        description: { lv: "vannasistabas skapīšu, spoguļskapju, izlietņu un cita aprīkojuma montāža." },
        status: "active",
        content: CONTENT["Vannasistabas meistars"] ?? null,
        services: [
        { id: "cm-s09-1", wId: "W099", name: { lv: "Vannasistabas skapīšu montāža" }, orderable: true },
        { id: "cm-s09-2", wId: "W100", name: { lv: "Spoguļskapja montāža" }, orderable: true },
        { id: "cm-s09-3", wId: "W101", name: { lv: "Izlietnes uzstādīšana vannas istabā" }, orderable: true },
        { id: "cm-s09-4", wId: "W102", name: { lv: "Cita vannasistabas aprīkojuma montāža" }, orderable: true },
        ],
      },
      {
        id: "cm-s10",
        categoryId: "cm-c1",
        name: { lv: "Santehnikas meistars" },
        description: { lv: "nelielu noplūžu novēršana, ūdensvada un kanalizācijas mezglu remonts atbilstoši kvalifikācijai." },
        status: "active",
        content: CONTENT["Santehnikas meistars"] ?? null,
        services: [
        { id: "cm-s10-1", wId: "W103", name: { lv: "Nelielas noplūdes novēršana" }, orderable: false },
        { id: "cm-s10-2", wId: "W104", name: { lv: "Ūdensvada mezgla remonts" }, orderable: false },
        { id: "cm-s10-3", wId: "W105", name: { lv: "Kanalizācijas mezgla remonts" }, orderable: false },
        ],
      },
      {
        id: "cm-s11",
        categoryId: "cm-c1",
        name: { lv: "Īpašumu uzturēšanas meistars" },
        description: { lv: "īres dzīvokļu apskate, nelielu defektu novēršana un mājokļu uzturēšanas darbi." },
        status: "active",
        content: CONTENT["Īpašumu uzturēšanas meistars"] ?? null,
        services: [
        { id: "cm-s11-1", wId: "W106", name: { lv: "Īres dzīvokļa apskate" }, orderable: true },
        { id: "cm-s11-2", wId: "W107", name: { lv: "Nelielu defektu novēršana" }, orderable: true },
        { id: "cm-s11-3", wId: "W108", name: { lv: "Mājokļa uzturēšanas darbi" }, orderable: true },
        ],
      },
      ],
    },
    {
      id: "cm-c2",
      name: { lv: "Specializētie meistari" },
      specialisations: [
      {
        id: "cm-s12",
        categoryId: "cm-c2",
        name: { lv: "Fūgu meistars" },
        description: { lv: "veco flīžu šuvju atjaunošana, tīrīšana un pāršuvošana." },
        status: "planned",
        content: CONTENT["Fūgu meistars"] ?? null,
        services: [
        { id: "cm-s12-1", wId: "W109", name: { lv: "Flīžu šuvju atjaunošana" }, orderable: false },
        { id: "cm-s12-2", wId: "W110", name: { lv: "Flīžu šuvju tīrīšana" }, orderable: false },
        { id: "cm-s12-3", wId: "W111", name: { lv: "Flīžu pāršuvošana" }, orderable: false },
        ],
      },
      {
        id: "cm-s13",
        categoryId: "cm-c2",
        name: { lv: "Elektrības meistars" },
        description: { lv: "rozešu, slēdžu, elektroinstalācijas un pieslēgumu darbi atbilstoši kvalifikācijai." },
        status: "planned",
        content: CONTENT["Elektrības meistars"] ?? null,
        services: [
        { id: "cm-s13-1", wId: "W112", name: { lv: "Rozešu darbi" }, orderable: false },
        { id: "cm-s13-2", wId: "W113", name: { lv: "Slēdžu darbi" }, orderable: false },
        { id: "cm-s13-3", wId: "W114", name: { lv: "Elektroinstalācijas darbi" }, orderable: false },
        { id: "cm-s13-4", wId: "W115", name: { lv: "Pieslēgumu darbi" }, orderable: false },
        ],
      },
      {
        id: "cm-s14",
        categoryId: "cm-c2",
        name: { lv: "Apkures meistars" },
        description: { lv: "radiatoru, termostatu, apkures cauruļu un sistēmu remonts un nomaiņa." },
        status: "planned",
        content: CONTENT["Apkures meistars"] ?? null,
        services: [
        { id: "cm-s14-1", wId: "W116", name: { lv: "Radiatora remonts vai nomaiņa" }, orderable: false },
        { id: "cm-s14-2", wId: "W117", name: { lv: "Termostata remonts vai nomaiņa" }, orderable: false },
        { id: "cm-s14-3", wId: "W118", name: { lv: "Apkures cauruļu remonts vai nomaiņa" }, orderable: false },
        { id: "cm-s14-4", wId: "W119", name: { lv: "Apkures sistēmas remonts vai nomaiņa" }, orderable: false },
        ],
      },
      {
        id: "cm-s15",
        categoryId: "cm-c2",
        name: { lv: "Logu meistars" },
        description: { lv: "logu regulēšana, furnitūras un blīvējumu remonts vai nomaiņa." },
        status: "planned",
        content: CONTENT["Logu meistars"] ?? null,
        services: [
        { id: "cm-s15-1", wId: "W120", name: { lv: "Logu regulēšana" }, orderable: false },
        { id: "cm-s15-2", wId: "W121", name: { lv: "Logu furnitūras remonts vai nomaiņa" }, orderable: false },
        { id: "cm-s15-3", wId: "W122", name: { lv: "Logu blīvējumu remonts vai nomaiņa" }, orderable: false },
        ],
      },
      {
        id: "cm-s16",
        categoryId: "cm-c2",
        name: { lv: "Durvju meistars" },
        description: { lv: "durvju regulēšana, uzstādīšana, slēdzeņu, rokturu un eņģu maiņa." },
        status: "planned",
        content: CONTENT["Durvju meistars"] ?? null,
        services: [
        { id: "cm-s16-1", wId: "W123", name: { lv: "Durvju regulēšana" }, orderable: false },
        { id: "cm-s16-2", wId: "W124", name: { lv: "Durvju uzstādīšana" }, orderable: false },
        { id: "cm-s16-3", wId: "W125", name: { lv: "Slēdzenes maiņa" }, orderable: false },
        { id: "cm-s16-4", wId: "W126", name: { lv: "Roktura maiņa" }, orderable: false },
        { id: "cm-s16-5", wId: "W127", name: { lv: "Eņģu maiņa" }, orderable: false },
        ],
      },
      {
        id: "cm-s17",
        categoryId: "cm-c2",
        name: { lv: "Ūdens skaitītāju meistars" },
        description: { lv: "skaitītāju maiņa atbilstoši nepieciešamajai kvalifikācijai." },
        status: "planned",
        content: CONTENT["Ūdens skaitītāju meistars"] ?? null,
        services: [
        { id: "cm-s17-1", wId: "W128", name: { lv: "Ūdens skaitītāja maiņa" }, orderable: false },
        ],
      },
      {
        id: "cm-s18",
        categoryId: "cm-c2",
        name: { lv: "Gāzes meistars" },
        description: { lv: "gāzes iekārtu un pieslēgumu darbi, tikai atbilstoši kvalificētam speciālistam." },
        status: "planned",
        content: CONTENT["Gāzes meistars"] ?? null,
        services: [
        { id: "cm-s18-1", wId: "W129", name: { lv: "Gāzes iekārtu darbi" }, orderable: false },
        { id: "cm-s18-2", wId: "W130", name: { lv: "Gāzes pieslēgumu darbi" }, orderable: false },
        ],
      },
      ],
    },
    {
      id: "cm-c3",
      name: { lv: "Papildu specializācijas" },
      specialisations: [
      {
        id: "cm-s19",
        categoryId: "cm-c3",
        name: { lv: "Bruģa mazgāšanas meistars" },
        description: { lv: "bruģa mazgāšana ar augstspiediena tehniku, netīrumu, sūnu un apauguma noņemšana." },
        status: "planned",
        content: CONTENT["Bruģa mazgāšanas meistars"] ?? null,
        services: [
        { id: "cm-s19-1", wId: "W131", name: { lv: "Bruģa mazgāšana ar augstspiediena tehniku" }, orderable: false },
        { id: "cm-s19-2", wId: "W132", name: { lv: "Netīrumu, sūnu un apauguma noņemšana no bruģa" }, orderable: false },
        ],
      },
      {
        id: "cm-s20",
        categoryId: "cm-c3",
        name: { lv: "Apdares meistars" },
        description: { lv: "sienu špaktelēšana, slīpēšana un krāsošana." },
        status: "planned",
        content: CONTENT["Apdares meistars"] ?? null,
        services: [
        { id: "cm-s20-1", wId: "W133", name: { lv: "Sienu špaktelēšana" }, orderable: false },
        { id: "cm-s20-2", wId: "W134", name: { lv: "Sienu slīpēšana" }, orderable: false },
        { id: "cm-s20-3", wId: "W135", name: { lv: "Sienu krāsošana" }, orderable: false },
        ],
      },
      {
        id: "cm-s21",
        categoryId: "cm-c3",
        name: { lv: "Flīzēšanas meistars" },
        description: { lv: "sienu un grīdu flīzēšana." },
        status: "planned",
        content: CONTENT["Flīzēšanas meistars"] ?? null,
        services: [
        { id: "cm-s21-1", wId: "W136", name: { lv: "Sienu flīzēšana" }, orderable: false },
        { id: "cm-s21-2", wId: "W137", name: { lv: "Grīdas flīzēšana" }, orderable: false },
        ],
      },
      {
        id: "cm-s22",
        categoryId: "cm-c3",
        name: { lv: "Grīdu meistars" },
        description: { lv: "lamināta, vinila un grīdlīstu ieklāšana un montāža." },
        status: "planned",
        content: CONTENT["Grīdu meistars"] ?? null,
        services: [
        { id: "cm-s22-1", wId: "W138", name: { lv: "Lamināta ieklāšana" }, orderable: false },
        { id: "cm-s22-2", wId: "W139", name: { lv: "Vinila grīdas ieklāšana" }, orderable: false },
        { id: "cm-s22-3", wId: "W140", name: { lv: "Grīdlīstu montāža" }, orderable: false },
        ],
      },
      {
        id: "cm-s23",
        categoryId: "cm-c3",
        name: { lv: "Ģipškartona meistars" },
        description: { lv: "ģipškartona konstrukciju izbūve un remonts." },
        status: "planned",
        content: CONTENT["Ģipškartona meistars"] ?? null,
        services: [
        { id: "cm-s23-1", wId: "W141", name: { lv: "Ģipškartona konstrukciju izbūve" }, orderable: false },
        { id: "cm-s23-2", wId: "W142", name: { lv: "Ģipškartona konstrukciju remonts" }, orderable: false },
        ],
      },
      {
        id: "cm-s24",
        categoryId: "cm-c3",
        name: { lv: "Remontdarbu meistars" },
        description: { lv: "dažādi dzīvokļu un mājokļu remonta darbi pēc konkrētās kompetences." },
        status: "planned",
        content: CONTENT["Remontdarbu meistars"] ?? null,
        services: [

        ],
      },
      ],
    },
  ],
}
