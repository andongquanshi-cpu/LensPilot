export type Filter = 'CPL'|'CLOSE_UP'|'BLACK_MIST'|'STAR'|'KEEP'|'CLEAR'
export interface Frame {frame_id:string;source_session_id:string;sequence:number;captured_at:number;received_at:number;source:string;actual_filter:Filter|null;simulated:boolean}
export interface Snapshot {
 device:{connection:string;motion:string;phase:string;actual_filter:Filter|null;target_filter:Filter|null;actual_slot:number|null;position_verified:boolean;auto:boolean;locked:boolean;analyzing:boolean;recording:string;recording_source:string;command_status:string;simulated:boolean;error:string|null;pending:unknown;state_version:number};
 source:{kind:string;status:string;session_id:string;sequence:number;simulated:boolean;label:string};
 model:{provider:string;model:string;simulated:boolean;status:string;scenario:string;latency_ms:number|null};
 frame:Frame|null;analysis:{subject:string;reason:string;recommended_filter:Filter;uncertainty:number}|null;analysis_frame:Frame|null;
 decision:{reason:string;target:Filter}|null;intent:{text:string;scope:string;preference:string};automatic_block:string|null;
 events:{event_id:string;timestamp:number;type:string;message:string}[];snapshots:Record<string,Frame>;server_time:number;
}
export interface Config {slots:Partial<Record<Filter,number>>;supports_clear:boolean;media_files:string[];camera_indices:number[];sample_seconds:number;consistent_count:number;cooldown_seconds:number;demo_distance_verified:boolean}
