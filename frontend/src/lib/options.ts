export const CARD_OPTIONS = [
  { name: 'HDFC Regalia', bank: 'HDFC', network: 'visa' },
  { name: 'HDFC Infinia', bank: 'HDFC', network: 'visa' },
  { name: 'HDFC Diners Black', bank: 'HDFC', network: 'diners' },
  { name: 'HDFC Millennia', bank: 'HDFC', network: 'visa' },
  { name: 'SBI SimplyCLICK', bank: 'SBI', network: 'visa' },
  { name: 'SBI Elite', bank: 'SBI', network: 'visa' },
  { name: 'SBI Prime', bank: 'SBI', network: 'visa' },
  { name: 'Axis Magnus', bank: 'Axis', network: 'visa' },
  { name: 'Axis Burgundy Private', bank: 'Axis', network: 'visa' },
  { name: 'Axis My Zone', bank: 'Axis', network: 'visa' },
  { name: 'ICICI Amazon Pay', bank: 'ICICI', network: 'visa' },
  { name: 'ICICI Emerald', bank: 'ICICI', network: 'visa' },
  { name: 'Yes First Exclusive', bank: 'Yes Bank', network: 'visa' },
  { name: 'Amex Platinum', bank: 'American Express', network: 'amex' },
  { name: 'Amex Platinum Travel', bank: 'American Express', network: 'amex' },
  { name: 'Amex Gold', bank: 'American Express', network: 'amex' },
  { name: 'Chase Sapphire Preferred', bank: 'Chase', network: 'visa' },
  { name: 'Chase Sapphire Reserve', bank: 'Chase', network: 'visa' },
] as const;

export const BANK_OPTIONS = [
  'HDFC', 'SBI', 'Axis', 'ICICI', 'American Express', 'Chase', 'Citi', 'Yes Bank', 'Kotak',
] as const;

export const AIRPORT_OPTIONS = [
  { code: 'BLR', label: 'Bengaluru, India' },
  { code: 'DEL', label: 'New Delhi, India' },
  { code: 'BOM', label: 'Mumbai, India' },
  { code: 'HYD', label: 'Hyderabad, India' },
  { code: 'MAA', label: 'Chennai, India' },
  { code: 'CCU', label: 'Kolkata, India' },
  { code: 'AMD', label: 'Ahmedabad, India' },
  { code: 'PNQ', label: 'Pune, India' },
  { code: 'COK', label: 'Kochi, India' },
  { code: 'GOI', label: 'Goa, India' },
  { code: 'JAI', label: 'Jaipur, India' },
  { code: 'ATQ', label: 'Amritsar, India' },
  { code: 'DXB', label: 'Dubai, UAE' },
  { code: 'AUH', label: 'Abu Dhabi, UAE' },
  { code: 'DOH', label: 'Doha, Qatar' },
  { code: 'SIN', label: 'Singapore' },
  { code: 'KUL', label: 'Kuala Lumpur, Malaysia' },
  { code: 'BKK', label: 'Bangkok, Thailand' },
  { code: 'HKG', label: 'Hong Kong' },
  { code: 'NRT', label: 'Tokyo Narita, Japan' },
  { code: 'HND', label: 'Tokyo Haneda, Japan' },
  { code: 'ICN', label: 'Seoul Incheon, South Korea' },
  { code: 'LHR', label: 'London Heathrow, UK' },
  { code: 'LGW', label: 'London Gatwick, UK' },
  { code: 'CDG', label: 'Paris Charles de Gaulle, France' },
  { code: 'AMS', label: 'Amsterdam, Netherlands' },
  { code: 'FRA', label: 'Frankfurt, Germany' },
  { code: 'MUC', label: 'Munich, Germany' },
  { code: 'ZRH', label: 'Zurich, Switzerland' },
  { code: 'FCO', label: 'Rome Fiumicino, Italy' },
  { code: 'MXP', label: 'Milan Malpensa, Italy' },
  { code: 'BCN', label: 'Barcelona, Spain' },
  { code: 'MAD', label: 'Madrid, Spain' },
  { code: 'IST', label: 'Istanbul, Turkey' },
  { code: 'JFK', label: 'New York JFK, USA' },
  { code: 'EWR', label: 'Newark/New York, USA' },
  { code: 'LGA', label: 'New York LaGuardia, USA' },
  { code: 'LAX', label: 'Los Angeles, USA' },
  { code: 'SFO', label: 'San Francisco, USA' },
  { code: 'SEA', label: 'Seattle, USA' },
  { code: 'ORD', label: 'Chicago O Hare, USA' },
  { code: 'DFW', label: 'Dallas Fort Worth, USA' },
  { code: 'ATL', label: 'Atlanta, USA' },
  { code: 'DEN', label: 'Denver, USA' },
  { code: 'PHX', label: 'Phoenix, USA' },
  { code: 'LAS', label: 'Las Vegas, USA' },
  { code: 'MIA', label: 'Miami, USA' },
  { code: 'BOS', label: 'Boston, USA' },
  { code: 'IAD', label: 'Washington Dulles, USA' },
  { code: 'YYZ', label: 'Toronto, Canada' },
  { code: 'YVR', label: 'Vancouver, Canada' },
  { code: 'SYD', label: 'Sydney, Australia' },
  { code: 'MEL', label: 'Melbourne, Australia' },
] as const;

export function findCardOption(name: string) {
  const normalized = name.trim().toLowerCase();
  return CARD_OPTIONS.find(card => card.name.toLowerCase() === normalized);
}

export function airportCode(value: string): string {
  return value.trim().slice(0, 3).toUpperCase();
}
