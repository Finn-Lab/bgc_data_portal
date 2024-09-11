
import pandas as pd


class BgcAggregator:
    """Find union/interection of BGCs from different detectors"""
    @staticmethod
    def aggregate_results(aggregated_bgcs):
        """Create a list of aggregagted regions given results from intersection and union functions"""
        aggregated_results = {}
        for group,aggregated_bgcs in aggregated_bgcs:
            base_values = dict(group)

            base_values['mgybs'] = list({mgyb for bgc in aggregated_bgcs for mgyb in bgc.mgybs})
            base_values['bgc_detector_names'] = list({detector for bgc in aggregated_bgcs for detector in bgc.bgc_detector_names})
            base_values['bgc_class_names'] = list({_class for bgc in aggregated_bgcs for _class in bgc.bgc_class_names})
            # base_values['partial'] =  # TODO. make sure partiality is recoreded for both sides

            for k,v in base_values.items():
                aggregated_results.setdefault(k,[]).append(v)
            
        return pd.DataFrame(aggregated_results)

    @staticmethod
    def single(individual_bgcs,n_detectors=2):
        return individual_bgcs

    @staticmethod
    def union(individual_bgcs,n_detectors=2):

        output_bgcs = []

        # Step 2: Process each group for overlapping regions
        for _,bgcs in individual_bgcs.groupby('mgyc_id'):
            
            if bgcs.shape[0]<n_detectors:
                continue

            # Sort bgcs by start_position to make it easier to detect overlaps
            bgcs.sort_values('start_position').reset_index(drop=True)

            current_group = bgcs.iloc[0]
            aggregated_bgcs = [current_group]

            for i in range(1, bgcs.shape[0]):
                bgc = bgcs.iloc[i]
                
                # Check if current bgc overlaps with the current group
                if bgc.start_position <= current_group.end_position:

                    current_group.end_position = max(current_group.end_position, bgc.end_position)
                    aggregated_bgcs.append(bgc)

                elif len(aggregated_bgcs)>=n_detectors:
                    
                    # If not overlapping, save the current group and start a new one
                    output_bgcs.append((current_group,aggregated_bgcs))
                    # Start a new group
                    current_group = bgc
                    aggregated_bgcs = [current_group]

            # Don't forget to add the last group
            if len(aggregated_bgcs)>=n_detectors:
                output_bgcs.append((current_group,aggregated_bgcs))

        return BgcAggregator.aggregate_results(output_bgcs)
    
    @staticmethod
    def intersection(individual_bgcs,n_detectors=2):

        output_bgcs = []

        # Step 2: Process each group for overlapping regions
        for _,bgcs in individual_bgcs.groupby('mgyc_id'):
            
            if bgcs.shape[0]<n_detectors:
                continue

            # Sort bgcs by start_position to make it easier to detect overlaps
            bgcs.sort_values('start_position').reset_index(drop=True)

            current_group = bgcs.iloc[0]
            aggregated_bgcs = [current_group]

            for i in range(1, bgcs.shape[0]):
                bgc = bgcs.iloc[i]
                
                # Check if the current bgc overlaps with the current group and has all detector names
                if bgc.start_position <= current_group.end_position:
                    
                    # Update the current group's end_position to the intersection
                    current_group.end_position = min(current_group.end_position, bgc.end_position)
                    current_group.start_position = max(current_group.start_position, bgc.start_position)
                    # Aggregate the values
                    aggregated_bgcs.append(bgc)

                elif len(aggregated_bgcs)>=n_detectors:
                    # If not overlapping, start a new group, or if it doesn't match all detector names, skip
                    output_bgcs.append((current_group,aggregated_bgcs))

                    current_group = bgc
                    aggregated_bgcs = [current_group]

            # Don't forget to add the last group if it meets the criteria
            if len(aggregated_bgcs)>=n_detectors:
                output_bgcs.append((current_group,aggregated_bgcs))

        return BgcAggregator.aggregate_results(output_bgcs) 